import re
from sqlalchemy import text
from extensions import db
from models.instruction import Instruction

def stem_russian_word(word: str) -> str:
    """Учет словоформ русского языка (например: 'паяльники' -> 'паяльник')"""
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    suffixes = (
        'ями', 'ами', 'ого', 'его', 'ому', 'ему', 'ах', 'ях',
        'ой', 'ей', 'ый', 'ий', 'ая', 'яя', 'ое', 'ее', 'ые', 'ие',
        'ам', 'ям', 'ом', 'ем', 'ов', 'ев', 'а', 'я', 'о', 'е', 'ы', 'и', 'у', 'ю'
    )
    for s in suffixes:
        if w.endswith(s) and len(w) - len(s) >= 3:
            return w[:-len(s)]
    return w

def search_instructions(owner_id: int, query_str: str, category_id=None):
    """
    Полнотекстовый поиск (FR-08, раздел 8.10 и 8.11 ТЗ):
    - Если подключена СУБД PostgreSQL 14+ с колонкой search_vector (GIN + словарь 'russian' + pg_trgm),
      выполняется нативный поиск через websearch_to_tsquery('russian', :q) и ранжирование ts_rank.
    - При локальной разработке на SQLite используется встроенный русскоязычный морфологический стеммер
      с теми же весами: Название (100) > Материалы/Инструменты/Теги (30) > Описание/Этапы (10).
    """
    if db.engine.dialect.name == 'postgresql':
        try:
            sql = """
                SELECT id,
                       ts_rank(search_vector, websearch_to_tsquery('russian', :q)) AS rank
                FROM instructions
                WHERE owner_id = :owner_id
                  AND (
                      search_vector @@ websearch_to_tsquery('russian', :q)
                      OR title ILIKE :like_q
                  )
                ORDER BY rank DESC, id DESC
            """
            rows = db.session.execute(
                text(sql),
                {'q': query_str, 'owner_id': owner_id, 'like_q': f'%{query_str}%'}
            ).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                inst_map = {
                    i.id: i for i in Instruction.query.filter(
                        Instruction.id.in_(ids),
                        Instruction.owner_id == owner_id
                    ).all()
                }
                ordered = [inst_map[i] for i in ids if i in inst_map]
                if category_id == 'none':
                    ordered = [i for i in ordered if i.category_id is None]
                elif str(category_id).isdigit():
                    ordered = [i for i in ordered if i.category_id == int(category_id)]
                return ordered
        except Exception:
            db.session.rollback()

    q_words = [stem_russian_word(w) for w in re.findall(r'\w+', query_str.lower()) if w]
    if not q_words:
        return []

    query = Instruction.query.filter_by(owner_id=owner_id)
    if category_id:
        if category_id == 'none':
            query = query.filter(Instruction.category_id.is_(None))
        elif str(category_id).isdigit():
            query = query.filter_by(category_id=int(category_id))

    results = []
    for inst in query.all():
        score = 0
        title_l = inst.title.lower()
        desc_l = (inst.description or '').lower()
        mats_l = " ".join(link.material.name.lower() for link in inst.material_links)
        tools_l = " ".join(t.name.lower() for t in inst.tools)
        tags_l = " ".join(t.name.lower() for t in inst.tags)
        steps_l = " ".join(s.text.lower() for s in inst.steps)

        for stem in q_words:
            if stem in title_l:
                score += 100
            if stem in mats_l or stem in tools_l or stem in tags_l:
                score += 30
            if stem in desc_l or stem in steps_l:
                score += 10

        if score > 0:
            results.append((score, inst))

    results.sort(key=lambda x: (-x[0], -x[1].id))
    return [item[1] for item in results]