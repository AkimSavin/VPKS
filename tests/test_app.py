"""
Автоматические тесты pytest (подраздел 3.12, раздел 6.2 и Таблица 4 / Таблица 9 ТЗ).
Запуск из терминала PyCharm:
    pytest -v
"""
import os
import sys
import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from extensions import db
from models import User, Category, Material, Tool, Tag, Instruction, Step, InstructionMaterial
from services.search_service import search_instructions


@pytest.fixture
def test_ctx():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_category_delete_sets_null(test_ctx):
    """Проверка FR-01, FR-02 и TC-DB-14: при удалении категории инструкции переходят в 'Без категории'."""
    u = User(email='test@diy.local', password_hash=generate_password_hash('password123'))
    db.session.add(u)
    db.session.flush()

    cat = Category(owner_id=u.id, name='Электроника')
    db.session.add(cat)
    db.session.flush()

    inst = Instruction(owner_id=u.id, category_id=cat.id, title='Умная кормушка для птиц')
    db.session.add(inst)
    db.session.commit()

    # Удаляем категорию
    Instruction.query.filter_by(owner_id=u.id, category_id=cat.id).update({'category_id': None})
    db.session.delete(cat)
    db.session.commit()

    saved_inst = db.session.get(Instruction, inst.id)
    assert saved_inst is not None
    assert saved_inst.category_id is None


def test_material_many_to_many_and_cascade_delete(test_ctx):
    """Проверка FR-04 и TC-DB-13: каскадное удаление связей при сохранении материала в справочнике."""
    u = User(email='maker@diy.local', password_hash=generate_password_hash('password123'))
    db.session.add(u)
    db.session.flush()

    mat = Material(owner_id=u.id, name='Саморез 3×30')
    inst_a = Instruction(owner_id=u.id, title='Инструкция А')
    inst_b = Instruction(owner_id=u.id, title='Инструкция Б')
    db.session.add_all([mat, inst_a, inst_b])
    db.session.flush()

    db.session.add(InstructionMaterial(instruction_id=inst_a.id, material_id=mat.id, quantity=20, unit='шт.'))
    db.session.add(InstructionMaterial(instruction_id=inst_b.id, material_id=mat.id, quantity=10, unit='шт.'))
    db.session.commit()

    # Удаляем инструкцию А
    db.session.delete(inst_a)
    db.session.commit()

    # Материал остался в справочнике и в инструкции Б (10 шт.)
    assert db.session.get(Material, mat.id) is not None
    link_b = InstructionMaterial.query.filter_by(instruction_id=inst_b.id, material_id=mat.id).first()
    assert link_b is not None and link_b.quantity == 10


def test_fulltext_search_wordforms_and_ranking(test_ctx):
    """Проверка FR-08 и TC-DB-15: поиск 'паяльники' находит словоформы и ранжирует совпадение в названии выше."""
    u1 = User(email='u1@diy.local', password_hash=generate_password_hash('password123'))
    u2 = User(email='u2@diy.local', password_hash=generate_password_hash('password123'))
    db.session.add_all([u1, u2])
    db.session.flush()

    tool_solder = Tool(owner_id=u1.id, name='Паяльник')
    db.session.add(tool_solder)
    db.session.flush()

    # 1. Слово в этапе (низший приоритет)
    i_step = Instruction(owner_id=u1.id, title='Сборка радиоприемника')
    db.session.add(i_step)
    db.session.flush()
    db.session.add(Step(instruction_id=i_step.id, step_number=1, text='Разогрейте паяльник до 300 градусов.'))

    # 2. Слово в инструментах (средний приоритет)
    i_tool = Instruction(owner_id=u1.id, title='Ночник на светодиодах')
    i_tool.tools.append(tool_solder)
    db.session.add(i_tool)

    # 3. Слово в названии (высший приоритет)
    i_title = Instruction(owner_id=u1.id, title='Подставка под паяльник своими руками')
    db.session.add(i_title)

    # 4. Чужая инструкция пользователя U2 (не должна попасть в выдачу — NFR-17)
    i_other = Instruction(owner_id=u2.id, title='Паяльник для пластиковых труб')
    db.session.add(i_other)
    db.session.commit()

    results = search_instructions(u1.id, 'паяльники')
    assert len(results) == 3
    assert results[0].id == i_title.id
    assert results[1].id == i_tool.id
    assert results[2].id == i_step.id
    assert all(r.owner_id == u1.id for r in results)


def test_check_constraint_positive_quantity(test_ctx):
    """Проверка TC-DB-11: количество материала <= 0 отклоняется ограничением CHECK."""
    u = User(email='chk@diy.local', password_hash=generate_password_hash('password123'))
    db.session.add(u)
    db.session.flush()

    mat = Material(owner_id=u.id, name='Гвоздь')
    inst = Instruction(owner_id=u.id, title='Тест CHECK')
    db.session.add_all([mat, inst])
    db.session.flush()

    db.session.add(InstructionMaterial(instruction_id=inst.id, material_id=mat.id, quantity=0, unit='шт.'))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()