redis: sh -c 'redis-cli ping >/dev/null 2>&1 && { echo "system redis already running, reusing it"; exec tail -f /dev/null; } || exec redis-server --port 6379 --save "" --appendonly no'
web: venv/bin/python app.py
worker: venv/bin/celery -A celery_app worker -B --pool=solo --loglevel=info
