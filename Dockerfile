FROM python:3.11 as build

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        curl \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip 
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["/bin/sh", "-c", "python -c 'import os,sys,time\nimport psycopg2\nhost=os.getenv(\"DATABASE_HOST\",\"localhost\")\nport=int(os.getenv(\"DATABASE_PORT\",\"5432\"))\ndb=os.getenv(\"DATABASE_NAME\",\"postgres\")\nuser=os.getenv(\"DATABASE_USER\",\"postgres\")\npwd=os.getenv(\"DATABASE_PASSWORD\",\"\")\nsslmode=os.getenv(\"DATABASE_SSLMODE\",\"disable\")\nattempts=int(os.getenv(\"DB_WAIT_ATTEMPTS\",\"60\"))\ndelay=float(os.getenv(\"DB_WAIT_DELAY\",\"2\"))\nfor i in range(attempts):\n    try:\n        conn=psycopg2.connect(host=host, port=port, dbname=db, user=user, password=pwd, sslmode=sslmode, connect_timeout=3)\n        conn.close()\n        sys.exit(0)\n    except Exception as e:\n        print(f\"DB belum siap ({i+1}/{attempts}): {e}\", file=sys.stderr)\n        time.sleep(delay)\nprint(\"DB belum siap (timeout)\", file=sys.stderr)\nsys.exit(1)\n' && python manage.py migrate --noinput --fake-initial && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${WORKERS:-3} --worker-class gthread --threads ${THREADS:-2} --timeout ${TIMEOUT:-120} --keep-alive ${KEEP_ALIVE:-65} --max-requests ${MAX_REQUESTS:-1000} --max-requests-jitter ${MAX_REQUESTS_JITTER:-50} --access-logfile ${ACCESS_LOGFILE:--} --error-logfile ${ERROR_LOGFILE:--} --log-level ${LOG_LEVEL:-info}"]
