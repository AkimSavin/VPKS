import os
import uuid
from flask import current_app
from extensions import db
from models.photo import Photo

def verify_and_save_photo(file_storage, instruction_id, step_id=None, is_cover=False):
    """Модуль фотографий (FR-06, NFR-20): проверка сигнатуры JPEG/PNG и лимита 5 МБ"""
    if not file_storage or not file_storage.filename:
        return None
    header = file_storage.read(16)
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)

    if size <= 0 or size > 5 * 1024 * 1024:
        raise ValueError("Размер файла должен быть от 1 байта до 5 МБ.")

    if header.startswith(b'\xff\xd8\xff'):
        mime, ext = 'image/jpeg', '.jpg'
    elif header.startswith(b'\x89PNG\r\n\x1a\n'):
        mime, ext = 'image/png', '.png'
    else:
        raise ValueError("Недопустимый формат файла. Разрешены только JPEG или PNG.")

    fname = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], fname)
    file_storage.save(filepath)

    if is_cover:
        Photo.query.filter_by(instruction_id=instruction_id, is_cover=True).update({'is_cover': False})

    photo = Photo(
        instruction_id=instruction_id,
        step_id=step_id,
        filename=fname,
        mime_type=mime,
        size_bytes=size,
        is_cover=is_cover
    )
    db.session.add(photo)
    return photo