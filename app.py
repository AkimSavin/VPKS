import os
import re
import sys
import logging
from datetime import datetime, timezone

from flask import (
    Flask, request, redirect, url_for, session, flash,
    send_from_directory, abort, render_template, current_app
)
from werkzeug.security import generate_password_hash

from config import Config, ALLOWED_UNITS
from extensions import db, migrate
from models import (
    User, Category, Material, Tool, Tag,
    Instruction, Step, Photo, InstructionMaterial, InstructionTag
)
from services.security import LOGIN_ATTEMPTS, generate_csrf_token, verify_csrf, login_required
from services.photo_service import verify_and_save_photo
from services.search_service import search_instructions
from services.seed_service import seed_demo_data_if_empty

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join('static', 'css'), exist_ok=True)
os.makedirs(os.path.join('static', 'js'), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('app_events.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

db.init_app(app)
if migrate is not None:
    migrate.init_app(app, db)
app.jinja_env.globals['csrf_token'] = generate_csrf_token
app.before_request(verify_csrf)


@app.before_request
def limit_upload_size():
    """Динамический контроль размера загружаемых файлов: 55 МБ для импорта PDF, 5 МБ для фото."""
    max_size = 55 * 1024 * 1024 if request.path == '/import' else 5 * 1024 * 1024
    if request.content_length and request.content_length > max_size:
        abort(413)


def get_user_instruction_or_404(inst_id: int) -> Instruction:
    inst = Instruction.query.get_or_404(inst_id)
    if inst.owner_id != session['user_id']:
        abort(404, description="Не найдено")
    return inst


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('main_menu'))

    email_val = ''
    if request.method == 'POST':
        action = request.form.get('action')
        email_val = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        ip = request.remote_addr or 'local'

        attempts_info = LOGIN_ATTEMPTS.get(ip, {'count': 0, 'blocked_until': 0})
        now_ts = datetime.now(timezone.utc).timestamp()
        if attempts_info['blocked_until'] > now_ts:
            flash("Превышен лимит попыток входа. Подождите 60 секунд.", "error")
            return render_template('login.html', email_val=email_val, bg_video='bg_login.mp4')

        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email_val):
            flash("Введите корректный адрес электронной почты (e-mail).", "error")
            return render_template('login.html', email_val=email_val, bg_video='bg_login.mp4')

        if len(password) < 8:
            flash("Пароль должен содержать не менее 8 символов.", "error")
            return render_template('login.html', email_val=email_val, bg_video='bg_login.mp4')

        if action == 'register':
            if User.query.filter_by(email=email_val).first():
                flash("Пользователь с таким e-mail уже зарегистрирован.", "error")
                return render_template('login.html', email_val=email_val, bg_video='bg_login.mp4')
            new_user = User(email=email_val, password_hash=generate_password_hash(password))
            db.session.add(new_user)
            db.session.commit()
            logging.info(f"REGISTER user_id={new_user.id} email={email_val}")
            session['user_id'] = new_user.id
            session['user_email'] = new_user.email
            session['just_logged_in'] = True
            session['just_registered'] = True
            flash("Аккаунт успешно создан! Добро пожаловать в мастерскую.", "success")
            return redirect(url_for('main_menu'))

        elif action == 'login':
            user = User.query.filter_by(email=email_val).first()
            if user and user.check_password(password):
                LOGIN_ATTEMPTS.pop(ip, None)
                session['user_id'] = user.id
                session['user_email'] = user.email
                session['just_logged_in'] = True
                logging.info(f"LOGIN_SUCCESS user_id={user.id}")
                return redirect(url_for('main_menu'))
            else:
                attempts_info['count'] += 1
                if attempts_info['count'] >= 5:
                    attempts_info['blocked_until'] = now_ts + 60
                    attempts_info['count'] = 0
                LOGIN_ATTEMPTS[ip] = attempts_info
                logging.warning(f"LOGIN_FAIL email={email_val} ip={ip}")
                flash("Неверный e-mail или пароль.", "error")

    return render_template('login.html', email_val=email_val, bg_video='bg_login.mp4')


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    uid = session.get('user_id')
    session.clear()
    logging.info(f"LOGOUT user_id={uid}")
    return redirect(url_for('login'))


@app.route('/menu')
@login_required
def main_menu():
    uid = session['user_id']
    total_inst = Instruction.query.filter_by(owner_id=uid).count()
    just_logged = session.pop('just_logged_in', False)
    just_registered = session.pop('just_registered', False)
    return render_template(
        'main_menu.html',
        total_inst=total_inst,
        just_logged=just_logged,
        just_registered=just_registered,
        bg_video='bg_menu.mp4'
    )


@app.route('/')
@login_required
def inventory():
    uid = session['user_id']
    q = (request.args.get('q') or '').strip()
    cat_filter = request.args.get('category_id') or ''
    tag_filter = request.args.get('tag_id') or ''
    just_logged = session.pop('just_logged_in', False)
    just_registered = session.pop('just_registered', False)

    categories = Category.query.filter_by(owner_id=uid).order_by(Category.name).all()
    tags = Tag.query.filter_by(owner_id=uid).order_by(Tag.name).all()

    if q:
        if len(q) > 100:
            flash("Поисковый запрос не должен превышать 100 символов.", "error")
            instructions = []
        else:
            instructions = search_instructions(uid, q, cat_filter if cat_filter else None)
    else:
        query = Instruction.query.filter_by(owner_id=uid)
        if cat_filter == 'none':
            query = query.filter(Instruction.category_id.is_(None))
        elif cat_filter.isdigit():
            query = query.filter_by(category_id=int(cat_filter))

        if tag_filter.isdigit():
            query = query.join(InstructionTag).filter(InstructionTag.tag_id == int(tag_filter))

        instructions = query.order_by(Instruction.updated_at.desc()).all()

    total_slots = max(27, ((len(instructions) // 9) + 1) * 9)
    empty_slots = total_slots - len(instructions)

    return render_template(
        'inventory.html',
        instructions=instructions,
        empty_slots=empty_slots,
        categories=categories,
        tags=tags,
        q=q,
        cat_filter=cat_filter,
        tag_filter=tag_filter,
        just_logged=just_logged,
        just_registered=just_registered,
        bg_video='bg_inventory.mp4'
    )


@app.route('/photos/<int:photo_id>')
@login_required
def serve_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    if photo.instruction.owner_id != session['user_id']:
        abort(404, description="Не найдено")
    if current_app.config.get('USE_X_ACCEL_REDIRECT'):
        response = current_app.response_class(status=200, mimetype=photo.mime_type)
        response.headers['X-Accel-Redirect'] = f"/protected_uploads/{photo.filename}"
        return response
    return send_from_directory(app.config['UPLOAD_FOLDER'], photo.filename)


@app.route('/instructions/new', methods=['GET', 'POST'])
@login_required
def create_instruction():
    uid = session['user_id']
    categories = Category.query.filter_by(owner_id=uid).order_by(Category.name).all()
    form_data = {'title': '', 'description': '', 'category_id': '', 'new_category': ''}

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        category_id = request.form.get('category_id') or ''
        new_category = (request.form.get('new_category') or '').strip()
        form_data = {'title': title, 'description': description, 'category_id': category_id, 'new_category': new_category}

        if not title or len(title) > 120:
            flash("Название инструкции обязательно и должно быть от 1 до 120 символов.", "error")
            return render_template('create_instruction.html', categories=categories, form=form_data, bg_video='bg_create.mp4')
        if len(description) > 5000:
            flash("Описание не должно превышать 5000 символов.", "error")
            return render_template('create_instruction.html', categories=categories, form=form_data, bg_video='bg_create.mp4')

        try:
            cat_obj = None
            if new_category:
                if len(new_category) > 60:
                    raise ValueError("Название новой категории не может превышать 60 символов.")
                cat_obj = Category.query.filter_by(owner_id=uid, name=new_category).first()
                if not cat_obj:
                    cat_obj = Category(owner_id=uid, name=new_category)
                    db.session.add(cat_obj)
                    db.session.flush()
            elif category_id.isdigit():
                cat_obj = Category.query.filter_by(id=int(category_id), owner_id=uid).first()

            inst = Instruction(
                owner_id=uid,
                category_id=cat_obj.id if cat_obj else None,
                title=title,
                description=description
            )
            db.session.add(inst)
            db.session.flush()

            cover_file = request.files.get('cover_photo')
            if cover_file and cover_file.filename:
                verify_and_save_photo(cover_file, inst.id, is_cover=True)

            db.session.commit()
            logging.info(f"CREATE_INSTRUCTION id={inst.id} user_id={uid}")
            flash("Инструкция создана! Теперь вы можете добавить материалы, инструменты и этапы.", "success")
            return redirect(url_for('view_instruction', inst_id=inst.id))
        except Exception as e:
            db.session.rollback()
            logging.error(f"CREATE_INST_ERROR user_id={uid}: {str(e)}")
            flash(str(e), "error")

    return render_template('create_instruction.html', categories=categories, form=form_data, bg_video='bg_create.mp4')


@app.route('/instructions/<int:inst_id>', methods=['GET', 'POST'])
@login_required
def view_instruction(inst_id):
    uid = session['user_id']
    inst = get_user_instruction_or_404(inst_id)

    if request.method == 'POST':
        form_type = request.form.get('form_type')
        try:
            if form_type == 'update_meta':
                title = (request.form.get('title') or '').strip()
                desc = (request.form.get('description') or '').strip()
                cat_id = request.form.get('category_id') or ''
                if not title or len(title) > 120:
                    raise ValueError("Название должно быть от 1 до 120 символов.")
                inst.title = title
                inst.description = desc[:5000]
                inst.category_id = int(cat_id) if cat_id.isdigit() else None

                cover_file = request.files.get('cover_photo')
                if cover_file and cover_file.filename:
                    verify_and_save_photo(cover_file, inst.id, is_cover=True)
                db.session.commit()
                flash("Основные данные инструкции обновлены.", "success")

            elif form_type == 'add_material':
                mat_name = (request.form.get('material_name') or '').strip()
                qty_raw = (request.form.get('quantity') or '').replace(',', '.')
                unit = request.form.get('unit') or 'шт.'
                if not mat_name or len(mat_name) > 100:
                    raise ValueError("Название материала должно быть от 1 до 100 символов.")
                try:
                    qty = round(float(qty_raw), 2)
                except ValueError:
                    raise ValueError("Количество должно быть положительным числом.")
                if qty <= 0:
                    raise ValueError("Количество материала должно быть строго больше нуля.")
                if unit not in ALLOWED_UNITS:
                    raise ValueError("Недопустимая единица измерения.")

                mat = Material.query.filter_by(owner_id=uid, name=mat_name).first()
                if not mat:
                    mat = Material(owner_id=uid, name=mat_name)
                    db.session.add(mat)
                    db.session.flush()

                link = InstructionMaterial.query.filter_by(instruction_id=inst.id, material_id=mat.id).first()
                if link:
                    link.quantity = qty
                    link.unit = unit
                else:
                    db.session.add(InstructionMaterial(instruction_id=inst.id, material_id=mat.id, quantity=qty, unit=unit))
                db.session.commit()
                flash(f"Материал «{mat.name}» ({qty} {unit}) сохранен в инструкции.", "success")

            elif form_type == 'remove_material':
                mat_id = int(request.form.get('material_id'))
                InstructionMaterial.query.filter_by(instruction_id=inst.id, material_id=mat_id).delete()
                db.session.commit()
                flash("Материал отвязан от инструкции (в справочнике сохранен).", "success")

            elif form_type == 'add_tool':
                tool_name = (request.form.get('tool_name') or '').strip()
                if not tool_name or len(tool_name) > 100:
                    raise ValueError("Название инструмента должно быть от 1 до 100 символов.")
                tool = Tool.query.filter_by(owner_id=uid, name=tool_name).first()
                if not tool:
                    tool = Tool(owner_id=uid, name=tool_name)
                    db.session.add(tool)
                    db.session.flush()
                if tool not in inst.tools:
                    inst.tools.append(tool)
                db.session.commit()
                flash(f"Инструмент «{tool.name}» привязан.", "success")

            elif form_type == 'remove_tool':
                t_id = int(request.form.get('tool_id'))
                tool = Tool.query.filter_by(id=t_id, owner_id=uid).first()
                if tool and tool in inst.tools:
                    inst.tools.remove(tool)
                    db.session.commit()
                flash("Инструмент отвязан от инструкции.", "success")

            elif form_type == 'add_tag':
                tag_name = (request.form.get('tag_name') or '').strip().lstrip('#')
                if not tag_name or len(tag_name) > 30:
                    raise ValueError("Метка (тег) должна быть от 1 до 30 символов.")
                tag = Tag.query.filter_by(owner_id=uid, name=tag_name).first()
                if not tag:
                    tag = Tag(owner_id=uid, name=tag_name)
                    db.session.add(tag)
                    db.session.flush()
                if tag not in inst.tags:
                    inst.tags.append(tag)
                db.session.commit()
                flash(f"Тег #{tag.name} добавлен.", "success")

            elif form_type == 'remove_tag':
                tag_id = int(request.form.get('tag_id'))
                tag = Tag.query.filter_by(id=tag_id, owner_id=uid).first()
                if tag and tag in inst.tags:
                    inst.tags.remove(tag)
                    db.session.commit()

            elif form_type == 'add_step':
                text = (request.form.get('step_text') or '').strip()
                if not text or len(text) > 2000:
                    raise ValueError("Текст этапа обязателен (от 1 до 2000 символов).")
                next_num = len(inst.steps) + 1
                step = Step(instruction_id=inst.id, step_number=next_num, text=text)
                db.session.add(step)
                db.session.flush()

                uploaded_files = request.files.getlist('step_photos')
                if not uploaded_files or not any(f.filename for f in uploaded_files):
                    single = request.files.get('step_photo')
                    if single and single.filename:
                        uploaded_files = [single]

                saved_count = 0
                for p_file in uploaded_files:
                    if p_file and p_file.filename:
                        verify_and_save_photo(p_file, inst.id, step_id=step.id, is_cover=False)
                        saved_count += 1

                db.session.commit()
                msg = f"Этап №{next_num} добавлен."
                if saved_count > 0:
                    msg += f" (Прикреплено фото: {saved_count} шт.)"
                flash(msg, "success")

            elif form_type == 'add_step_photos_existing':
                step_id = int(request.form.get('step_id'))
                step = Step.query.filter_by(id=step_id, instruction_id=inst.id).first_or_404()
                files = request.files.getlist('additional_photos')
                count = 0
                for f in files:
                    if f and f.filename:
                        verify_and_save_photo(f, inst.id, step_id=step.id, is_cover=False)
                        count += 1
                db.session.commit()
                flash(f"К этапу №{step.step_number} добавлено фотографий: {count} шт.", "success")

            elif form_type == 'delete_photo':
                photo_id = int(request.form.get('photo_id'))
                photo = Photo.query.filter_by(id=photo_id, instruction_id=inst.id).first_or_404()
                fname = photo.filename
                db.session.delete(photo)
                db.session.commit()
                fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
                flash("Фотография этапа успешно удалена.", "success")

            elif form_type == 'move_step':
                step_id = int(request.form.get('step_id'))
                direction = request.form.get('direction')
                steps = list(inst.steps)
                idx = next((i for i, s in enumerate(steps) if s.id == step_id), None)
                if idx is not None:
                    swap_idx = idx - 1 if direction == 'up' else idx + 1
                    if 0 <= swap_idx < len(steps):
                        s1, s2 = steps[idx], steps[swap_idx]
                        n1, n2 = s1.step_number, s2.step_number
                        s1.step_number = -999
                        db.session.flush()
                        s2.step_number = n1
                        db.session.flush()
                        s1.step_number = n2
                        db.session.commit()

            elif form_type == 'delete_step':
                step_id = int(request.form.get('step_id'))
                step_photos = Photo.query.filter_by(step_id=step_id, instruction_id=inst.id).all()
                file_names_to_del = [p.filename for p in step_photos]

                Step.query.filter_by(id=step_id, instruction_id=inst.id).delete()
                db.session.flush()

                for fname in file_names_to_del:
                    fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass

                remaining = Step.query.filter_by(instruction_id=inst.id).order_by(Step.step_number).all()
                for idx, st in enumerate(remaining):
                    st.step_number = -(idx + 1)
                db.session.flush()
                for idx, st in enumerate(remaining):
                    st.step_number = idx + 1
                db.session.commit()
                flash("Этап удален, нумерация пересчитана.", "success")

        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")

        return redirect(url_for('view_instruction', inst_id=inst.id))

    categories = Category.query.filter_by(owner_id=uid).order_by(Category.name).all()
    all_materials = Material.query.filter_by(owner_id=uid).order_by(Material.name).all()
    all_tools = Tool.query.filter_by(owner_id=uid).order_by(Tool.name).all()
    return render_template(
        'view_instruction.html',
        inst=inst,
        categories=categories,
        all_materials=all_materials,
        all_tools=all_tools,
        units=ALLOWED_UNITS,
        bg_video='bg_inventory.mp4'
    )


@app.route('/instructions/<int:inst_id>/delete', methods=['POST'])
@login_required
def delete_instruction(inst_id):
    inst = get_user_instruction_or_404(inst_id)
    uid = session['user_id']
    photo_files = [p.filename for p in inst.photos]
    db.session.delete(inst)
    db.session.commit()

    for fname in photo_files:
        fpath = os.path.join(app.config['UPLOAD_FOLDER'], fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    logging.info(f"DELETE_INSTRUCTION id={inst_id} user_id={uid}")
    flash("Инструкция и все её этапы и фотографии удалены (справочники сохранены).", "success")
    return redirect(url_for('inventory'))


@app.route('/instructions/<int:inst_id>/read', methods=['GET', 'POST'])
@login_required
def read_instruction(inst_id):
    inst = get_user_instruction_or_404(inst_id)
    steps = list(inst.steps)
    if not steps:
        flash("В этой инструкции пока нет этапов для пошагового режима.", "error")
        return redirect(url_for('view_instruction', inst_id=inst.id))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'mark_done':
            step_id = int(request.form.get('step_id'))
            st = Step.query.filter_by(id=step_id, instruction_id=inst.id).first()
            if st:
                st.mark_completed()
                db.session.commit()
                next_num = st.step_number + 1 if st.step_number < len(steps) else st.step_number
                return redirect(url_for('read_instruction', inst_id=inst.id, step=next_num))
        elif action == 'reset_progress':
            Step.query.filter_by(instruction_id=inst.id).update({'is_completed': False})
            db.session.commit()
            flash("Прогресс выполнения сброшен.", "success")
            return redirect(url_for('read_instruction', inst_id=inst.id, step=1))
        return redirect(url_for('read_instruction', inst_id=inst.id))

    step_num_param = request.args.get('step')
    if step_num_param and step_num_param.isdigit():
        current_step = next((s for s in steps if s.step_number == int(step_num_param)), steps[0])
    else:
        current_step = next((s for s in steps if not s.is_completed), steps[-1])

    return render_template('read_step.html', inst=inst, current_step=current_step, steps=steps, bg_video='bg_inventory.mp4')


@app.route('/categories', methods=['GET', 'POST'])
@login_required
def categories_view():
    uid = session['user_id']
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'create':
                name = (request.form.get('name') or '').strip()
                if not name or len(name) > 60:
                    raise ValueError("Название категории должно быть от 1 до 60 символов.")
                if Category.query.filter_by(owner_id=uid, name=name).first():
                    raise ValueError("Категория с таким названием у вас уже есть.")
                db.session.add(Category(owner_id=uid, name=name))
                db.session.commit()
                flash(f"Категория «{name}» создана.", "success")

            elif action == 'rename':
                cat_id = int(request.form.get('cat_id'))
                new_name = (request.form.get('new_name') or '').strip()
                cat = Category.query.filter_by(id=cat_id, owner_id=uid).first_or_404()
                if not new_name or len(new_name) > 60:
                    raise ValueError("Название категории должно быть от 1 до 60 символов.")
                cat.name = new_name
                db.session.commit()
                flash("Категория переименована.", "success")

            elif action == 'delete':
                cat_id = int(request.form.get('cat_id'))
                cat = Category.query.filter_by(id=cat_id, owner_id=uid).first_or_404()
                Instruction.query.filter_by(owner_id=uid, category_id=cat.id).update({'category_id': None})
                db.session.delete(cat)
                db.session.commit()
                flash(f"Категория «{cat.name}» удалена. Её инструкции переведены в «Без категории».", "success")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
        return redirect(url_for('categories_view'))

    cats = Category.query.filter_by(owner_id=uid).order_by(Category.name).all()
    return render_template('categories.html', categories=cats, bg_video='bg_menu.mp4')


@app.route('/catalogs', methods=['GET', 'POST'])
@login_required
def catalogs_view():
    uid = session['user_id']
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'add_mat':
                name = (request.form.get('name') or '').strip()
                if not name or len(name) > 100:
                    raise ValueError("Название материала: от 1 до 100 символов.")
                db.session.add(Material(owner_id=uid, name=name))
                db.session.commit()
                flash("Материал добавлен в справочник.", "success")
            elif action == 'del_mat':
                m_id = int(request.form.get('id'))
                mat = Material.query.filter_by(id=m_id, owner_id=uid).first_or_404()
                if mat.instruction_links:
                    raise ValueError(f"Нельзя удалить материал «{mat.name}» из справочника, так как он используется в инструкциях!")
                db.session.delete(mat)
                db.session.commit()
                flash("Материал удален из справочника.", "success")
            elif action == 'add_tool':
                name = (request.form.get('name') or '').strip()
                if not name or len(name) > 100:
                    raise ValueError("Название инструмента: от 1 до 100 символов.")
                db.session.add(Tool(owner_id=uid, name=name))
                db.session.commit()
                flash("Инструмент добавлен в справочник.", "success")
            elif action == 'del_tool':
                t_id = int(request.form.get('id'))
                tool = Tool.query.filter_by(id=t_id, owner_id=uid).first_or_404()
                if tool.instructions:
                    raise ValueError(f"Нельзя удалить инструмент «{tool.name}», так как он привязан к инструкциям!")
                db.session.delete(tool)
                db.session.commit()
                flash("Инструмент удален из справочника.", "success")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
        return redirect(url_for('catalogs_view'))

    materials = Material.query.filter_by(owner_id=uid).order_by(Material.name).all()
    tools = Tool.query.filter_by(owner_id=uid).order_by(Tool.name).all()
    return render_template('catalogs.html', materials=materials, tools=tools, bg_video='bg_menu.mp4')


@app.route('/recommendations', methods=['GET', 'POST'])
@login_required
def recommendations_view():
    uid = session['user_id']
    materials = Material.query.filter_by(owner_id=uid).order_by(Material.name).all()
    tools = Tool.query.filter_by(owner_id=uid).order_by(Tool.name).all()
    instructions = Instruction.query.filter_by(owner_id=uid).all()

    have_mat_ids = set(map(int, request.form.getlist('have_materials'))) if request.method == 'POST' else set()
    have_tool_ids = set(map(int, request.form.getlist('have_tools'))) if request.method == 'POST' else set()
    shop_inst_ids = set(map(int, request.form.getlist('shop_instructions'))) if request.method == 'POST' else set()

    recommendations = []
    for inst in instructions:
        missing_mats = [
            f"{link.material.name} ({link.quantity} {link.unit})"
            for link in inst.material_links if link.material_id not in have_mat_ids
        ]
        missing_tools = [t.name for t in inst.tools if t.id not in have_tool_ids]
        recommendations.append({
            'inst': inst,
            'missing_mats': missing_mats,
            'missing_tools': missing_tools,
            'can_build_now': len(missing_mats) == 0 and len(missing_tools) == 0
        })

    shopping_totals = {}
    for inst in instructions:
        if inst.id in shop_inst_ids:
            for link in inst.material_links:
                key = (link.material.name, link.unit)
                shopping_totals[key] = round(shopping_totals.get(key, 0.0) + link.quantity, 2)

    return render_template(
        'recommendations.html',
        materials=materials,
        tools=tools,
        instructions=instructions,
        have_mat_ids=have_mat_ids,
        have_tool_ids=have_tool_ids,
        shop_inst_ids=shop_inst_ids,
        recommendations=recommendations,
        shopping_totals=shopping_totals,
        bg_video='bg_menu.mp4'
    )


@app.route('/import', methods=['GET', 'POST'])
@login_required
def import_web():
    uid = session['user_id']
    if request.method == 'POST':
        import_type = request.form.get('import_type') or 'url'
        try:
            from services.import_service import parse_and_create_from_url, parse_and_create_from_file

            if import_type == 'file':
                file_obj = request.files.get('import_file')
                if not file_obj or not file_obj.filename:
                    flash("Пожалуйста, выберите файл .pdf, .json или .txt для загрузки.", "error")
                    return render_template('import_web.html', bg_video='bg_create.mp4')
                inst = parse_and_create_from_file(file_obj, uid)
                logging.info(f"IMPORT_FILE user_id={uid} inst_id={inst.id}")
                flash(f"Инструкция «{inst.title}» успешно создана из файла!", "success")
                return redirect(url_for('view_instruction', inst_id=inst.id))

            else:
                url = (request.form.get('url') or '').strip()
                if not url.startswith(('http://', 'https://')):
                    flash("Укажите корректную ссылку, начинающуюся с http:// или https://", "error")
                    return render_template('import_web.html', bg_video='bg_create.mp4')
                inst = parse_and_create_from_url(url, uid)
                logging.info(f"IMPORT_URL user_id={uid} inst_id={inst.id} url={url}")
                flash(f"Инструкция «{inst.title}» успешно собрана и сохранена!", "success")
                return redirect(url_for('view_instruction', inst_id=inst.id))

        except Exception as e:
            db.session.rollback()
            logging.error(f"IMPORT_ERROR user_id={uid}: {str(e)}")
            flash(f"Ошибка при импорте: {str(e)}", "error")

    return render_template('import_web.html', bg_video='bg_create.mp4')


@app.errorhandler(404)
def handle_404(err):
    return render_template(
        'error.html',
        title='404 — Не найдено',
        message='Запрошенный объект не существует или принадлежит другому пользователю.',
        bg_video='bg_menu.mp4'
    ), 404


@app.errorhandler(413)
def handle_413(err):
    flash("Файл слишком большой. Максимум: 5 МБ для фотографий и 55 МБ для PDF-инструкций.", "error")
    return redirect(request.referrer or url_for('inventory'))


@app.errorhandler(Exception)
def handle_500(err):
    logging.error(f"UNHANDLED_ERROR: {repr(err)}")
    return render_template(
        'error.html',
        title='Произошла внутренняя ошибка',
        message='Сведения записаны в системный журнал. Ваши данные в безопасности.',
        bg_video='bg_menu.mp4'
    ), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_demo_data_if_empty()
    print("\n" + "=" * 65)
    print(" Сервер запущен! Откройте в браузере: http://127.0.0.1:5000")
    print(" Тестовый вход: alexey@diy.local | Пароль: password123")
    print("=" * 65 + "\n", flush=True)
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)