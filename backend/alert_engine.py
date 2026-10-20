from .database import get_connection
from .utils import zscore, running_stats

# -- Global safety thresholds (hard limits, any patient) ----------------------
GLOBAL = {
    'hr':          {'low': 45,   'high': 130},
    'spo2':        {'low': 90,   'high': 100},
    'temperature': {'low': 35.0, 'high': 39.0},
    'movement':    {'still': 0.04},        # below = possible immobility
}

# Personal baseline: alert when zscore exceeds this multiplier
BASELINE_SIGMA = 2.5

# Multi-signal fusion: minimum signals that must agree before alert fires
FUSION_MIN_SIGNALS = 2


# -- Baseline helpers -----------------------------------------------------------

def get_baseline(patient_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        'SELECT * FROM baselines WHERE patient_id = ?', (patient_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_baseline(patient_id: int, hr: float, spo2: float, temp: float):
    """Welford online update -- no raw history stored."""
    conn = get_connection()
    b = conn.execute(
        'SELECT * FROM baselines WHERE patient_id = ?', (patient_id,)
    ).fetchone()

    if b is None:
        conn.execute('''
            INSERT INTO baselines
                (patient_id, hr_mean, hr_std, spo2_mean, spo2_std,
                 temp_mean, temp_std, reading_count)
            VALUES (?, ?, 10.0, ?, 1.5, ?, 0.3, 1)
        ''', (patient_id, hr, spo2, temp))
    else:
        n = b['reading_count']
        hr_m,   hr_s,   _ = running_stats(b['hr_mean'],   b['hr_std'],   n, hr)
        spo2_m, spo2_s, _ = running_stats(b['spo2_mean'], b['spo2_std'], n, spo2)
        tm,     ts,     _ = running_stats(b['temp_mean'], b['temp_std'], n, temp)
        conn.execute('''
            UPDATE baselines
            SET hr_mean=?, hr_std=?, spo2_mean=?, spo2_std=?,
                temp_mean=?, temp_std=?, reading_count=?
            WHERE patient_id=?
        ''', (hr_m, hr_s, spo2_m, spo2_s, tm, ts, n + 1, patient_id))

    conn.commit()
    conn.close()


# -- Multi-signal fusion ---------------------------------------------------------

def check_multi_signal_anomaly(
    hr: float, spo2: float, temperature: float,
    movement: float, baseline: dict | None
):
    """
    Returns (is_anomaly: bool, signal_count: int, signals: list[str])

    Fusion rule: at least FUSION_MIN_SIGNALS must fire independently.
    A single noisy reading can never trigger an alert on its own.
    """
    fired = []

    # -- 1. Global threshold checks ------------------------------------------
    if not (GLOBAL['hr']['low'] <= hr <= GLOBAL['hr']['high']):
        fired.append('HR_global')
    if spo2 < GLOBAL['spo2']['low']:
        fired.append('SpO2_global')
    if not (GLOBAL['temperature']['low'] <= temperature <= GLOBAL['temperature']['high']):
        fired.append('Temp_global')
    if movement < GLOBAL['movement']['still']:
        fired.append('Movement_immobile')

    # -- 2. Personal baseline deviation (only after >= 10 readings) ---------
    if baseline and baseline['reading_count'] >= 10:
        if zscore(hr,          baseline['hr_mean'],   baseline['hr_std'])   > BASELINE_SIGMA:
            fired.append('HR_baseline')
        if zscore(spo2,        baseline['spo2_mean'], baseline['spo2_std']) > BASELINE_SIGMA:
            fired.append('SpO2_baseline')
        if zscore(temperature, baseline['temp_mean'], baseline['temp_std']) > BASELINE_SIGMA:
            fired.append('Temp_baseline')

    # Deduplicate by signal type (global + baseline for same signal = 1 vote)
    unique_signals = list({s.split('_')[0] for s in fired})
    is_anomaly = len(unique_signals) >= FUSION_MIN_SIGNALS

    return is_anomaly, len(unique_signals), unique_signals


# -- Tiered alert level -----------------------------------------------------------

def determine_alert_level(score: float, is_anomaly: bool, signals: list) -> int:
    """
    0 -> No alert
    1 -> Local buzzer          (mild)
    2 -> SMS via GSM / 2G      (moderate)
    3 -> Push notification     (critical -- cloud when online)
    """
    if not is_anomaly:
        return 0
    if score >= 0.85 or len(signals) >= 3:
        return 3
    if score >= 0.60 or len(signals) >= 2:
        return 2
    return 1
