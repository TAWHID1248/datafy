#!/usr/bin/env bash
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py run_worker &
exec gunicorn datafy.wsgi --bind 0.0.0.0:"${PORT:-8000}" --workers 2 --timeout 120
