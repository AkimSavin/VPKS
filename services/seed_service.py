from werkzeug.security import generate_password_hash
from extensions import db
from models import User, Category, Material, Tool, Tag, Instruction, InstructionMaterial, Step

def seed_demo_data_if_empty():
    if User.query.first() is not None:
        return
    u1 = User(email='alexey@diy.local', password_hash=generate_password_hash('password123'))
    db.session.add(u1)
    db.session.flush()

    cat_elec = Category(owner_id=u1.id, name='Электроника')
    cat_wood = Category(owner_id=u1.id, name='Столярное дело')
    db.session.add_all([cat_elec, cat_wood])
    db.session.flush()

    m_screw = Material(owner_id=u1.id, name='Саморез 3×30')
    m_esp = Material(owner_id=u1.id, name='Плата ESP32')
    m_wood = Material(owner_id=u1.id, name='Фанера 6 мм')
    db.session.add_all([m_screw, m_esp, m_wood])

    t_solder = Tool(owner_id=u1.id, name='Паяльник')
    t_driver = Tool(owner_id=u1.id, name='Шуруповёрт')
    db.session.add_all([t_solder, t_driver])

    tag_solder = Tag(owner_id=u1.id, name='пайка')
    tag_iot = Tag(owner_id=u1.id, name='esp32')
    db.session.add_all([tag_solder, tag_iot])
    db.session.flush()

    inst1 = Instruction(
        owner_id=u1.id,
        category_id=cat_elec.id,
        title='Умная кормушка для птиц на ESP32',
        description='Автоматическая кормушка с датчиком веса и уведомлениями. Используется микроэлектроника и 3D-печать.'
    )
    inst1.tools.extend([t_solder, t_driver])
    inst1.tags.extend([tag_solder, tag_iot])
    db.session.add(inst1)
    db.session.flush()

    db.session.add(InstructionMaterial(instruction_id=inst1.id, material_id=m_screw.id, quantity=20, unit='шт.'))
    db.session.add(InstructionMaterial(instruction_id=inst1.id, material_id=m_esp.id, quantity=1, unit='шт.'))
    db.session.add(Step(instruction_id=inst1.id, step_number=1, text='Распечатать корпус дозатора и подготовить плату ESP32.', is_completed=True))
    db.session.add(Step(instruction_id=inst1.id, step_number=2, text='Распаять провода питания и сервопривода.', is_completed=False))
    db.session.add(Step(instruction_id=inst1.id, step_number=3, text='Собрать корпус саморезами 3×30 и проверить подачу корма.', is_completed=False))

    inst2 = Instruction(
        owner_id=u1.id,
        category_id=cat_wood.id,
        title='Деревянная подставка под паяльник и катушку припоя',
        description='Удобный органайзер для рабочего стола в мастерской.'
    )
    inst2.tools.append(t_driver)
    inst2.tags.append(tag_solder)
    db.session.add(inst2)
    db.session.flush()

    db.session.add(InstructionMaterial(instruction_id=inst2.id, material_id=m_screw.id, quantity=10, unit='шт.'))
    db.session.add(InstructionMaterial(instruction_id=inst2.id, material_id=m_wood.id, quantity=0.5, unit='м'))
    db.session.add(Step(instruction_id=inst2.id, step_number=1, text='Выпилить основание из фанеры 6 мм и скрутить держатель.', is_completed=False))

    db.session.commit()