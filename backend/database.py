import sqlite3
import os

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'health.db')


def db_path() -> str:
    # HEALTH_DB_PATH points the app at a different database file: a
    # persistent disk in production (e.g. /var/data/health.db), or a
    # throwaway file for ml/evaluate.py's eval harness and the tests.
    return os.path.abspath(os.environ.get('HEALTH_DB_PATH', DEFAULT_DB_PATH))


def get_connection():
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # timeout: wait for a lock instead of failing when several threads write
    # at once (gunicorn runs the API with multiple threads).
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout = 15000')
    return conn


def init_db():
    conn = get_connection()
    # WAL lets the dashboard read while a device is writing.
    conn.execute('PRAGMA journal_mode = WAL')
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            age         INTEGER,
            health_id   TEXT    UNIQUE,
            is_demo     INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS vitals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id    INTEGER NOT NULL,
            timestamp     TEXT    DEFAULT (datetime('now')),
            hr            REAL,
            spo2          REAL,
            temperature   REAL,
            movement      REAL,
            anomaly_score REAL    DEFAULT 0.0,
            is_anomaly    INTEGER DEFAULT 0,
            alert_level   INTEGER DEFAULT 0,
            source        TEXT    DEFAULT 'live_device',
            device_id     TEXT,
            synced        INTEGER DEFAULT 1,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS baselines (
            patient_id    INTEGER PRIMARY KEY,
            hr_mean       REAL    DEFAULT 75.0,
            hr_std        REAL    DEFAULT 10.0,
            spo2_mean     REAL    DEFAULT 97.0,
            spo2_std      REAL    DEFAULT 1.5,
            temp_mean     REAL    DEFAULT 37.0,
            temp_std      REAL    DEFAULT 0.3,
            reading_count INTEGER DEFAULT 0,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        )
    ''')

    # Migrate older databases created before the 'source' / 'is_demo' columns existed.
    existing_vitals_cols = {row['name'] for row in c.execute('PRAGMA table_info(vitals)')}
    if 'source' not in existing_vitals_cols:
        c.execute("ALTER TABLE vitals ADD COLUMN source TEXT DEFAULT 'live_device'")
    if 'device_id' not in existing_vitals_cols:
        c.execute("ALTER TABLE vitals ADD COLUMN device_id TEXT")

    existing_patient_cols = {row['name'] for row in c.execute('PRAGMA table_info(patients)')}
    if 'is_demo' not in existing_patient_cols:
        c.execute("ALTER TABLE patients ADD COLUMN is_demo INTEGER DEFAULT 0")

    conn.commit()
    conn.close()
    print("[DB] Tables initialised.")
