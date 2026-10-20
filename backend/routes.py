import hmac
import math
from datetime import datetime

from flask import Blueprint, request, jsonify

from . import config
from .database import get_connection
from .ingest import process_and_store_reading
from .alert_engine import get_baseline

api = Blueprint('api', __name__)

# How long (seconds) a device is still considered "live" after its last
# reading before the dashboard falls back to the default clinical-dataset view.
LIVE_TIMEOUT_SECONDS = config.LIVE_TIMEOUT_SECONDS

# Upper bound on ?limit= so one request can't dump the whole table.
MAX_LIMIT = 1000


# -- Optional API-key protection ----------------------------------------------
# When API_KEY is set in the environment, every /api/* request must send it
# in an `X-API-Key` header. Unset (local development) = open access.

@api.before_request
def _require_api_key():
    if config.API_KEY is None:
        return None
    supplied = request.headers.get('X-API-Key', '')
    if not hmac.compare_digest(supplied, config.API_KEY):
        return jsonify({'error': 'Missing or invalid X-API-Key header'}), 401
    return None


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _number(value, field):
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field}' must be a number")
    if not math.isfinite(x):
        raise ValueError(f"'{field}' must be a finite number")
    return x


def _patient_exists(patient_id: int) -> bool:
    conn = get_connection()
    row = conn.execute('SELECT 1 FROM patients WHERE id = ?', (patient_id,)).fetchone()
    conn.close()
    return row is not None


# -- Patients ------------------------------------------------------------------

@api.route('/patients', methods=['GET'])
def list_patients():
    conn = get_connection()
    rows = [dict(r) for r in conn.execute('SELECT * FROM patients').fetchall()]
    conn.close()
    return jsonify(rows), 200


@api.route('/patient', methods=['POST'])
def add_patient():
    data = _json_body()
    if not data or not str(data.get('name', '')).strip():
        return jsonify({'error': 'name is required'}), 400
    health_id = (data.get('health_id') or '').strip() or None

    conn = get_connection()
    try:
        cur = conn.execute(
            'INSERT INTO patients (name, age, health_id, is_demo) VALUES (?, ?, ?, 0)',
            (str(data['name']).strip(), data.get('age'), health_id)
        )
        conn.commit()
    except Exception as exc:
        conn.close()
        if 'UNIQUE' in str(exc):
            return jsonify({'error': 'A patient with that health_id already exists'}), 409
        raise
    patient_id = cur.lastrowid
    conn.close()
    return jsonify({'status': 'created', 'patient_id': patient_id}), 201


# -- Vitals ingestion (this is the endpoint an Arduino / ESP32 / STM32 board,
#    or the USB serial bridge, POSTs live sensor readings to) -----------------

@api.route('/vitals', methods=['POST'])
def ingest_vitals():
    data = _json_body()
    required = ['patient_id', 'hr', 'spo2', 'temperature']
    if not data or not all(k in data for k in required):
        return jsonify({'error': f'Required fields: {required}'}), 400

    try:
        patient_id = int(data['patient_id'])
        hr = _number(data['hr'], 'hr')
        spo2 = _number(data['spo2'], 'spo2')
        temperature = _number(data['temperature'], 'temperature')
        movement = _number(data.get('movement', 0.5), 'movement')
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400

    if not _patient_exists(patient_id):
        return jsonify({'error': f'patient_id {patient_id} does not exist -- '
                                 f'create it first with POST /api/patient'}), 404

    source = data.get('source', 'live_device')
    if source not in {'live_device', 'manual'}:
        source = 'live_device'

    result = process_and_store_reading(
        patient_id=patient_id,
        hr=hr,
        spo2=spo2,
        temperature=temperature,
        movement=movement,
        source=source,
        device_id=(str(data['device_id'])[:64] if data.get('device_id') else None),
    )
    return jsonify(result), 200


# -- Vitals retrieval ------------------------------------------------------------

@api.route('/vitals/<int:patient_id>', methods=['GET'])
def get_vitals(patient_id):
    limit = max(1, min(request.args.get('limit', 100, type=int), MAX_LIMIT))
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        'SELECT * FROM vitals WHERE patient_id=? ORDER BY timestamp DESC LIMIT ?',
        (patient_id, limit)
    ).fetchall()]
    conn.close()
    return jsonify(rows), 200


@api.route('/alerts/<int:patient_id>', methods=['GET'])
def get_alerts(patient_id):
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(
        '''SELECT * FROM vitals WHERE patient_id=? AND is_anomaly=1
           ORDER BY timestamp DESC LIMIT 20''',
        (patient_id,)
    ).fetchall()]
    conn.close()
    return jsonify(rows), 200


@api.route('/baseline/<int:patient_id>', methods=['GET'])
def get_patient_baseline(patient_id):
    b = get_baseline(patient_id)
    if not b:
        return jsonify({'message': 'No baseline collected yet.'}), 404
    return jsonify(b), 200


# -- Live device status ---------------------------------------------------------
# The dashboard polls this on every refresh to decide whether to show the
# default clinical-dataset demo view or auto-switch to a live board's feed.

@api.route('/live_status', methods=['GET'])
def live_status():
    conn = get_connection()
    row = conn.execute('''
        SELECT patient_id, device_id, timestamp
        FROM vitals
        WHERE source = 'live_device'
        ORDER BY timestamp DESC
        LIMIT 1
    ''').fetchone()
    conn.close()

    if not row:
        return jsonify({'live': False}), 200

    try:
        last_seen = datetime.fromisoformat(row['timestamp'])
        age_seconds = (datetime.now() - last_seen).total_seconds()
    except (TypeError, ValueError):
        age_seconds = 9999

    is_live = age_seconds <= LIVE_TIMEOUT_SECONDS
    return jsonify({
        'live': is_live,
        'patient_id': row['patient_id'] if is_live else None,
        'device_id': row['device_id'] if is_live else None,
        'last_seen': row['timestamp'],
        'seconds_since_last_reading': round(age_seconds, 1),
    }), 200
