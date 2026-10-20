"""
backend/ingest.py
------------------
Single shared pipeline that turns one raw vitals reading into a stored,
scored row: Kalman filter -> adaptive baseline update -> ML prediction ->
multi-signal fusion -> tiered alert -> persist.

Used by:
  * routes.py's POST /api/vitals  (readings pushed live from an
    Arduino / ESP32 / STM32 board, or via the serial bridge)
  * data/seed_clinical_data.py    (bulk-loads the real PhysioNet clinical
    dataset at first boot so the dashboard has a populated default view)

Keeping this in one place guarantees the demo (clinical-dataset) rows and
the live device rows are scored identically.
"""
from datetime import datetime

from .database import get_connection
from .model import predict
from .alert_engine import (
    check_multi_signal_anomaly, determine_alert_level,
    get_baseline, update_baseline,
)
from .utils import KalmanFilter1D

# Per-patient Kalman filters kept in memory for the process lifetime.
_kf: dict = {}


def _get_kf(patient_id: int) -> dict:
    if patient_id not in _kf:
        _kf[patient_id] = {
            'hr':   KalmanFilter1D(measurement_variance=1.0),
            'spo2': KalmanFilter1D(measurement_variance=0.05),
            'temp': KalmanFilter1D(measurement_variance=0.01),
        }
    return _kf[patient_id]


def process_and_store_reading(
    patient_id: int,
    hr: float,
    spo2: float,
    temperature: float,
    movement: float = 0.5,
    source: str = 'live_device',
    device_id: str | None = None,
    timestamp: str | None = None,
):
    """
    Runs one raw reading through the full pipeline and persists it.
    `source` is one of: 'live_device' (Arduino/ESP32/STM32 board),
    'clinical_dataset' (seeded PhysioNet demo data), or 'manual'.
    Returns the same summary dict the HTTP API responds with.
    """
    kf = _get_kf(patient_id)
    f_hr   = round(kf['hr'].update(float(hr)), 2)
    f_spo2 = round(kf['spo2'].update(float(spo2)), 2)
    f_temp = round(kf['temp'].update(float(temperature)), 3)

    update_baseline(patient_id, f_hr, f_spo2, f_temp)
    baseline = get_baseline(patient_id)

    ml_anomaly, ml_score = predict(f_hr, f_spo2, f_temp, movement)

    fusion_anomaly, sig_count, signals = check_multi_signal_anomaly(
        f_hr, f_spo2, f_temp, movement, baseline
    )

    final_anomaly = bool(ml_anomaly or fusion_anomaly)
    final_score = round(max(ml_score, sig_count / 4.0), 4)
    alert_level = determine_alert_level(final_score, final_anomaly, signals)

    ts = timestamp or datetime.now().isoformat()

    conn = get_connection()
    conn.execute('''
        INSERT INTO vitals
            (patient_id, timestamp, hr, spo2, temperature, movement,
             anomaly_score, is_anomaly, alert_level, source, device_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (patient_id, ts, f_hr, f_spo2, f_temp, movement,
          final_score, int(final_anomaly), alert_level, source, device_id))
    conn.commit()
    conn.close()

    return {
        'status':            'ok',
        'filtered':          {'hr': f_hr, 'spo2': f_spo2, 'temperature': f_temp},
        'anomaly':           final_anomaly,
        'anomaly_score':     final_score,
        'alert_level':       alert_level,
        'signals_triggered': signals,
        'baseline_readings': baseline['reading_count'] if baseline else 0,
        'source':            source,
    }
