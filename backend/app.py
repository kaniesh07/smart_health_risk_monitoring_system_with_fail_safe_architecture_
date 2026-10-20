import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from . import config
from .database import init_db, get_connection, db_path
from .model import load_model
from .routes import api

try:                      # file locking is POSIX-only; on Windows (local dev,
    import fcntl          # single process) seeding simply runs unlocked.
except ImportError:       # pragma: no cover
    fcntl = None


def _seed_clinical_dataset_if_empty():
    """
    On first boot (empty patients table) load the bundled real clinical
    dataset (PhysioNet/CinC 2019 Challenge ICU vitals -- see data/README.md)
    so the dashboard has a populated, real, default view the moment it's
    opened.

    Guarded by a file lock so that several gunicorn workers booting at the
    same time can't seed the dataset twice.
    """
    if not config.SEED_DEMO_DATA:
        return

    lock_path = db_path() + '.seed.lock'
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, 'w') as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            conn = get_connection()
            count = conn.execute('SELECT COUNT(*) AS n FROM patients').fetchone()['n']
            conn.close()
            if count > 0:
                return
            try:
                from data.seed_clinical_data import seed
                seed()
            except Exception as exc:  # pragma: no cover - seeding must never crash boot
                print(f"[SEED] Skipped clinical dataset seeding: {exc}")
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.json.sort_keys = False

    # Boot sequence
    init_db()
    load_model()
    _seed_clinical_dataset_if_empty()

    flask_app.register_blueprint(api, url_prefix='/api')

    @flask_app.route('/')
    def index():
        return {'status': 'Smart Health Monitor API is running'}, 200

    @flask_app.route('/healthz')
    def healthz():
        """Liveness/readiness probe for Docker and hosting platforms."""
        try:
            conn = get_connection()
            conn.execute('SELECT 1').fetchone()
            conn.close()
        except Exception as exc:
            return {'status': 'error', 'detail': str(exc)}, 503
        return {'status': 'ok'}, 200

    # Always answer in JSON, never an HTML error page -- devices and the
    # dashboard parse every response as JSON.
    @flask_app.errorhandler(HTTPException)
    def _http_error(exc):
        return jsonify({'error': exc.name, 'detail': exc.description}), exc.code

    @flask_app.errorhandler(Exception)
    def _unhandled(exc):
        flask_app.logger.exception(exc)
        return jsonify({'error': 'Internal Server Error'}), 500

    return flask_app


# Module-level app object so `gunicorn backend.app:app` (see Procfile) and
# `flask --app backend.app run` both work without extra configuration.
app = create_app()


if __name__ == '__main__':
    app.run(debug=config.DEBUG, host='0.0.0.0', port=config.PORT)
