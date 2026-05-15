import os

bind = "0.0.0.0:8000"
# Малый VPS (~1 ГБ RAM): 2×1 воркер обычно достаточно для викторины.
# Переопределение на сервере: GUNICORN_WORKERS / GUNICORN_THREADS в .env
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "1"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
