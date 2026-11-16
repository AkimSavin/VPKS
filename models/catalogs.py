from sqlalchemy import UniqueConstraint
from extensions import db


class Category(db.Model):
    """Класс Категория (раздел 8.9 ТЗ)"""
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    name = db.Column(db.String(60), nullable=False)

    __table_args__ = (UniqueConstraint('owner_id', 'name', name='uq_cat_owner_name'),)


class Material(db.Model):
    """Класс Материал (раздел 8.9 ТЗ)"""
    __tablename__ = 'materials'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    name = db.Column(db.String(100), nullable=False)

    instruction_links = db.relationship('InstructionMaterial', back_populates='material')

    __table_args__ = (UniqueConstraint('owner_id', 'name', name='uq_mat_owner_name'),)


class Tool(db.Model):
    """Класс Инструмент (раздел 8.9 ТЗ)"""
    __tablename__ = 'tools'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    name = db.Column(db.String(100), nullable=False)

    __table_args__ = (UniqueConstraint('owner_id', 'name', name='uq_tool_owner_name'),)


class Tag(db.Model):
    """Класс Тег (раздел 8.9 ТЗ)"""
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    name = db.Column(db.String(30), nullable=False)

    __table_args__ = (UniqueConstraint('owner_id', 'name', name='uq_tag_owner_name'),)