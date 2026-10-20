"""
Gunicorn settings for the backend API (picked up via --config).

ONE worker process with several threads, on purpose: the per-patient
Kalman filters live in process memory (backend/ingest.py), so readings
from a device must all land in the same process. Threads still let the
API serve the dashboard and several devices concurrently.
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = 1
threads = int(os.environ.get('GUNICORN_THREADS', '4'))
worker_class = 'gthread'
timeout = 120          # first boot seeds the demo dataset
graceful_timeout = 30
preload_app = True     # init DB / load model / seed once, before serving
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info')
