-- ============================================================================
-- Схема базы данных «Мои DIY-инструкции» (11 таблиц, 3НФ, раздел 3.12 и 8.10 ТЗ)
-- Основная СУБД: PostgreSQL 14+ (с поддержкой tsvector, GIN и pg_trgm).
-- Примечание по совместимости с подразделом 8.10 ТЗ (таблица 9, MySQL 8.0.16+):
-- ограничения UNIQUE, NOT NULL, FOREIGN KEY (CASCADE / RESTRICT / SET NULL) и CHECK
-- идентичны для PostgreSQL 14+ и MySQL 8.0.16+ (utf8mb4_0900_as_ci).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL CHECK (email LIKE '%_@_%._%'),
    password_hash VARCHAR(255) NOT NULL,
    tariff VARCHAR(50) DEFAULT 'basic',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(60) NOT NULL CHECK (LENGTH(TRIM(name)) > 0),
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS instructions (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    title VARCHAR(120) NOT NULL CHECK (LENGTH(TRIM(title)) > 0),
    description VARCHAR(5000),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    search_vector TSVECTOR
);

-- Полнотекстовый индекс GIN + триграммный индекс pg_trgm (подраздел 3.12 и 8.11 ТЗ)
CREATE INDEX IF NOT EXISTS idx_instructions_search_vector ON instructions USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_instructions_title_trgm ON instructions USING GIN (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS steps (
    id SERIAL PRIMARY KEY,
    instruction_id INTEGER NOT NULL REFERENCES instructions(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL CHECK (step_number >= 1),
    text VARCHAR(2000) NOT NULL CHECK (LENGTH(TRIM(text)) > 0),
    is_completed BOOLEAN DEFAULT FALSE NOT NULL,
    UNIQUE (instruction_id, step_number),
    UNIQUE (instruction_id, id)
);

CREATE TABLE IF NOT EXISTS materials (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL CHECK (LENGTH(TRIM(name)) > 0),
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS tools (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(100) NOT NULL CHECK (LENGTH(TRIM(name)) > 0),
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    name VARCHAR(30) NOT NULL CHECK (LENGTH(TRIM(name)) > 0),
    UNIQUE (owner_id, name)
);

CREATE TABLE IF NOT EXISTS instruction_materials (
    instruction_id INTEGER NOT NULL REFERENCES instructions(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    quantity NUMERIC(10, 2) NOT NULL CHECK (quantity > 0),
    unit VARCHAR(10) NOT NULL CHECK (unit IN ('шт.', 'м', 'см', 'мм', 'кг', 'г', 'л', 'мл', 'уп.')),
    PRIMARY KEY (instruction_id, material_id)
);

CREATE TABLE IF NOT EXISTS instruction_tools (
    instruction_id INTEGER NOT NULL REFERENCES instructions(id) ON DELETE CASCADE,
    tool_id INTEGER NOT NULL REFERENCES tools(id) ON DELETE RESTRICT,
    PRIMARY KEY (instruction_id, tool_id)
);

CREATE TABLE IF NOT EXISTS instruction_tags (
    instruction_id INTEGER NOT NULL REFERENCES instructions(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (instruction_id, tag_id)
);

CREATE TABLE IF NOT EXISTS photos (
    id SERIAL PRIMARY KEY,
    instruction_id INTEGER NOT NULL REFERENCES instructions(id) ON DELETE CASCADE,
    step_id INTEGER REFERENCES steps(id) ON DELETE CASCADE,
    filename VARCHAR(255) UNIQUE NOT NULL,
    mime_type VARCHAR(50) NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png')),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
    is_cover BOOLEAN DEFAULT FALSE NOT NULL
);

-- Функция обновления поискового вектора с весами (FR-08: A - название, B - ресурсы/теги, C - описание/этапы)
CREATE OR REPLACE FUNCTION refresh_instruction_search_vector(target_inst_id INT)
RETURNS VOID AS $$
DECLARE
    v_title TEXT;
    v_desc TEXT;
    v_steps TEXT;
    v_mats TEXT;
    v_tools TEXT;
    v_tags TEXT;
BEGIN
    SELECT title, COALESCE(description, '') INTO v_title, v_desc
    FROM instructions WHERE id = target_inst_id;
    IF NOT FOUND THEN RETURN; END IF;

    SELECT COALESCE(string_agg(text, ' '), '') INTO v_steps FROM steps WHERE instruction_id = target_inst_id;
    SELECT COALESCE(string_agg(m.name, ' '), '') INTO v_mats
    FROM instruction_materials im JOIN materials m ON m.id = im.material_id WHERE im.instruction_id = target_inst_id;
    SELECT COALESCE(string_agg(t.name, ' '), '') INTO v_tools
    FROM instruction_tools it JOIN tools t ON t.id = it.tool_id WHERE it.instruction_id = target_inst_id;
    SELECT COALESCE(string_agg(tg.name, ' '), '') INTO v_tags
    FROM instruction_tags itg JOIN tags tg ON tg.id = itg.tag_id WHERE itg.instruction_id = target_inst_id;

    UPDATE instructions
    SET search_vector =
        setweight(to_tsvector('russian', COALESCE(v_title, '')), 'A') ||
        setweight(to_tsvector('russian', COALESCE(v_mats || ' ' || v_tools || ' ' || v_tags, '')), 'B') ||
        setweight(to_tsvector('russian', COALESCE(v_desc || ' ' || v_steps, '')), 'C')
    WHERE id = target_inst_id;
END;
$$ LANGUAGE plpgsql;