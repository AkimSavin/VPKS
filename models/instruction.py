from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, UniqueConstraint
from extensions import db
from config import ALLOWED_UNITS


class InstructionMaterial(db.Model):
    """Ассоциативный класс МатериалИнструкции (связь М:М с количеством и единицей измерения)"""
    __tablename__ = 'instruction_materials'
    instruction_id = db.Column(db.Integer, db.ForeignKey('instructions.id', ondelete='CASCADE'), primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('materials.id', ondelete='RESTRICT'), primary_key=True)
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(10), nullable=False)

    material = db.relationship('Material', back_populates='instruction_links')
    instruction = db.relationship('Instruction', back_populates='material_links')

    __table_args__ = (
        CheckConstraint('quantity > 0', name='chk_quantity_pos'),
        CheckConstraint(f"unit IN {ALLOWED_UNITS}", name='chk_unit_enum'),
    )


class InstructionTool(db.Model):
    """Связующая таблица Инструкции_Инструменты"""
    __tablename__ = 'instruction_tools'
    instruction_id = db.Column(db.Integer, db.ForeignKey('instructions.id', ondelete='CASCADE'), primary_key=True)
    tool_id = db.Column(db.Integer, db.ForeignKey('tools.id', ondelete='RESTRICT'), primary_key=True)


class InstructionTag(db.Model):
    """Связующая таблица Инструкции_Теги"""
    __tablename__ = 'instruction_tags'
    instruction_id = db.Column(db.Integer, db.ForeignKey('instructions.id', ondelete='CASCADE'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)


class Instruction(db.Model):
    """Класс Инструкция (раздел 8.9 ТЗ)"""
    __tablename__ = 'instructions'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id', ondelete='SET NULL'), nullable=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(5000), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    category = db.relationship('Category')
    steps = db.relationship('Step', backref='instruction', cascade='all, delete-orphan', order_by='Step.step_number')
    photos = db.relationship('Photo', backref='instruction', cascade='all, delete-orphan')
    material_links = db.relationship('InstructionMaterial', back_populates='instruction', cascade='all, delete-orphan')
    tools = db.relationship('Tool', secondary='instruction_tools', backref='instructions')
    tags = db.relationship('Tag', secondary='instruction_tags', backref='instructions')

    @property
    def cover_photo(self):
        return next((p for p in self.photos if p.is_cover), None)

    @property
    def progress(self):
        total = len(self.steps)
        if total == 0:
            return 0, 0, 0
        done = sum(1 for s in self.steps if s.is_completed)
        return done, total, int((done / total) * 100)


class Step(db.Model):
    """Класс Этап (раздел 8.9 ТЗ)"""
    __tablename__ = 'steps'
    id = db.Column(db.Integer, primary_key=True)
    instruction_id = db.Column(db.Integer, db.ForeignKey('instructions.id', ondelete='CASCADE'), nullable=False)
    step_number = db.Column(db.Integer, nullable=False)
    text = db.Column(db.String(2000), nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)

    photos = db.relationship('Photo', backref='step', cascade='all, delete-orphan')

    __table_args__ = (UniqueConstraint('instruction_id', 'step_number', name='uq_step_num'),)

    def mark_completed(self):
        self.is_completed = True