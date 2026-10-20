# One image, two services: the Flask API (default) and the Streamlit
# dashboard (override the command -- see docker-compose.yml / render.yaml).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5000 \
    HEALTH_DB_PATH=/data/health.db

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Make sure the trained model matches the installed scikit-learn exactly
# (deterministic: fixed seed, ~1 s).
RUN python -m ml.train_model > /dev/null

# Run as an unprivileged user; /data holds the SQLite database (mount a
# volume there to keep data across restarts).
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

EXPOSE 5000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"5000\")}/healthz', timeout=4)" || exit 1

CMD ["gunicorn", "backend.app:app", "--config", "gunicorn.conf.py"]
