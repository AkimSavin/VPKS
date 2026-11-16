import uuid
import logging
from functools import wraps
from flask import session, request, redirect, url_for, abort

LOGIN_ATTEMPTS = {}

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = uuid.uuid4().hex
    return session['_csrf_token']

def verify_csrf():
    if request.method == "POST":
        token = session.get('_csrf_token')
        form_token = request.form.get('csrf_token')
        if not token or token != form_token:
            logging.warning(f"CSRF mismatch from IP {request.remote_addr}")
            abort(403, description="Ошибка безопасности: неверный CSRF-токен.")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated