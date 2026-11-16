import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-pixel-craft-secret-key-2026')
    # По ТЗ (п. 3.12, 8.10): основная СУБД PostgreSQL 14+ (например: postgresql+psycopg2://user:pass@localhost:5432/diy_db)
    # Для локальной разработки на Windows в PyCharm по умолчанию используется локальная БД SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(BASE_DIR, 'diy_minecraft.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'uploads')
    # Глобальный лимит увеличен до 55 МБ для загрузки PDF-инструкций.
    # Строгий лимит 5 МБ для обычных фото контролируется в app.py и photo_service.py (FR-06, NFR-20)
    MAX_CONTENT_LENGTH = 55 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    # Включение отдачи защищенных фотографий через Nginx X-Accel-Redirect (раздел 8.5, 8.11 ТЗ)
    USE_X_ACCEL_REDIRECT = os.environ.get('USE_X_ACCEL_REDIRECT', '0') == '1'


ALLOWED_UNITS = ('шт.', 'м', 'см', 'мм', 'кг', 'г', 'л', 'мл', 'уп.')