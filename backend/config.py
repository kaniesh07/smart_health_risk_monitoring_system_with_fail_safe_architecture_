"""
backend/config.py
------------------
All deployment-time settings, read from environment variables so the same
code runs unchanged on a laptop, in Docker, or on Render / Railway / Heroku.

See `.env.example` at the project root for the full list.
"""
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


# Port the backend listens on. Hosting platforms inject $PORT.
PORT = int(os.environ.get('PORT', '5000'))

# Never run the Werkzeug debugger in production -- it allows remote code
# execution. Only enable locally with FLASK_DEBUG=1.
DEBUG = _bool('FLASK_DEBUG', False)

# Optional shared secret. When set, every /api/* request must carry it in an
# `X-API-Key` header (the dashboard, simulator, serial bridge and ESP32
# firmware all support this). Leave unset for local development.
API_KEY = os.environ.get('API_KEY', '').strip() or None

# Seed the bundled PhysioNet demo dataset into an empty database on boot.
SEED_DEMO_DATA = _bool('SEED_DEMO_DATA', True)

# Seconds a device counts as "live" after its last reading.
LIVE_TIMEOUT_SECONDS = int(os.environ.get('LIVE_TIMEOUT_SECONDS', '20'))
