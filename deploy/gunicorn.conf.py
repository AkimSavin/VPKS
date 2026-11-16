import multiprocessing

# Конфигурация WSGI-сервера Gunicorn (подраздел 3.12 и 8.11 ТЗ: NFR-15 — не менее 20 пользователей)
bind = "127.0.0.1:8000"
workers = max(2, multiprocessing.cpu_count() * 2 + 1)
threads = 2
timeout = 30
accesslog = "gunicorn_access.log"
errorlog = "app_events.log"
loglevel = "info"