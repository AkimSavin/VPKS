from datetime import datetime, timezone
from werkzeug.security import check_password_hash
from extensions import db

class User(db.Model):
    """Класс Пользователь (раздел 8.9 ТЗ)"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    tariff = db.Column(db.String(50), default='basic')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)