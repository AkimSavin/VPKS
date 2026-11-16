from extensions import db

class Photo(db.Model):
    """Класс Фотография (раздел 8.9 ТЗ)"""
    __tablename__ = 'photos'
    id = db.Column(db.Integer, primary_key=True)
    instruction_id = db.Column(db.Integer, db.ForeignKey('instructions.id', ondelete='CASCADE'), nullable=False)
    step_id = db.Column(db.Integer, db.ForeignKey('steps.id', ondelete='CASCADE'), nullable=True)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    mime_type = db.Column(db.String(50), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    is_cover = db.Column(db.Boolean, default=False, nullable=False)