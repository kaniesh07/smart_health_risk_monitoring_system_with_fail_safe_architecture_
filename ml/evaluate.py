"""
ml/evaluate.py
----------------
End-to-end evaluation of the deployed detection pipeline (not just the raw
ML classifier in isolation) -- every prediction below is produced by
calling the exact same backend.ingest.process_and_store_reading() function
the live API uses, against an isolated throwaway database (HEALTH_DB_PATH
env var), so production data is never touched.

Metrics computed, and how:

  Accuracy, Macro F1, Recall, Specificity, Confusion Matrix
      -> sklearn, on a synthetic held-out test set (seed different from
         training) run through the FULL pipeline (Kalman + baseline +
         ML + fusion), not the raw classifier.

  Critical-risk Recall / Missed Critical Event Rate
      -> same test set, restricted to rows tagged "critical" in
         ml/synthetic_data.py (SpO2/Temp/HR hard red-flag scenarios).

  False Alarm Rate
      -> reported TWICE: (a) on the synthetic normal test rows, and
         (b) on the REAL clinical dataset (all 5 sourced patients are
         non-septic, i.e. all true negatives -- see data/README.md --
         so "% flagged" there IS a valid real-world false-alarm measure,
         even though we can't measure real-world recall from this sample
         since it contains no positive/critical cases).

  End-to-End Alert Latency
      -> wall-clock time of each process_and_store_reading() call
         (Kalman filter + baseline read/update + ML predict + fusion +
         DB write). This is COMPUTE-PIPELINE latency only -- it does not
         include real network transmission time from an actual
         ESP32/Arduino board, which needs real hardware to measure.

  Personalization/Fusion improvement (%)
      -> ablation: the same test set scored twice -- (A) naive
         global-threshold-only, single-signal trigger (no personalized
         baseline, no ML, no fusion requirement) vs (B) the full system.
         Reported as % change in Macro F1, critical recall, and false
         alarm rate.

  Power Consumption
      -> NOT measured (no physical hardware in this environment). Given
         as a datasheet-based estimate for the firmware in
         firmware/esp32_vitals_client.ino, both as currently written
         (always-on, no sleep) and for an optional duty-cycled version.
         Needs real bench validation (e.g. an INA219 in-circuit) before
         being treated as ground truth.

Run from project root (after `python -m ml.train_model`):
    python -m ml.evaluate
Writes ml/evaluation_report.md and prints the same report to stdout.
"""
import os
import csv
import json
import shutil
import time

import numpy as np
from sklearn.metrics import (
    accuracy_score, f1_score, recall_score, confusion_matrix,
)

EVAL_DB_DIR = os.path.join(os.path.dirname(__file__), '_eval_tmp')
EVAL_DB_PATH = os.path.join(EVAL_DB_DIR, 'health_eval.db')

# Point the backend at a throwaway DB before importing anything that
# touches it -- get_connection() reads this env var on every call.
os.environ['HEALTH_DB_PATH'] = EVAL_DB_PATH

from backend.database import init_db, get_connection          # noqa: E402
from backend.model import load_model                            # noqa: E402
from backend.ingest import process_and_store_reading, _kf       # noqa: E402
from backend.alert_engine import GLOBAL                          # noqa: E402
from ml.synthetic_data import generate_dataset                   # noqa: E402

N_PER_CLASS_TEST = 300      # -> 600 test rows (300 normal + 300 anomaly)
N_CALIBRATION = 15          # pure-normal warm-up readings per patient, to
                             # establish a personal baseline (>=10 required
                             # for alert_engine to use it) before scoring
N_VIRTUAL_PATIENTS = 6
EVAL_SEED = 123              # different from training's SEED=42 -> genuinely held out
REAL_CSV = os.path.join(os.path.dirname(__file__), '..', 'data', 'clinical_dataset.csv')
REPORT_PATH = os.path.join(os.path.dirname(__file__), 'evaluation_report.md')


# ---------------------------------------------------------------------------
# Isolated DB + virtual patients
# ---------------------------------------------------------------------------

def fresh_eval_db():
    shutil.rmtree(EVAL_DB_DIR, ignore_errors=True)
    os.makedirs(EVAL_DB_DIR, exist_ok=True)
    init_db()


def make_virtual_patients(n):
    conn = get_connection()
    ids = []
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO patients (name, age, health_id, is_demo) VALUES (?, ?, ?, 0)",
            (f"Eval-Patient-{i}", 60, f"EVAL-{i}")
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


# ---------------------------------------------------------------------------
# Config A: naive global-threshold-only detector (the ablation baseline)
# No personalization, no ML, no multi-signal fusion requirement -- fires
# on ANY single global threshold breach. This represents the kind of
# bare-minimum system the personalization+fusion+ML pipeline improves on.
# ---------------------------------------------------------------------------

def global_only_predict(hr, spo2, temperature, movement):
    if not (GLOBAL['hr']['low'] <= hr <= GLOBAL['hr']['high']):
        return 1
    if spo2 < GLOBAL['spo2']['low']:
        return 1
    if not (GLOBAL['temperature']['low'] <= temperature <= GLOBAL['temperature']['high']):
        return 1
    if movement < GLOBAL['movement']['still']:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Run the full pipeline (Config B) over the synthetic test set
# ---------------------------------------------------------------------------

def run_full_pipeline_eval():
    rng = np.random.default_rng(EVAL_SEED + 1)  # calibration draws, separate stream
    X_test, y_test, crit_test = generate_dataset(n_per_class=N_PER_CLASS_TEST, seed=EVAL_SEED)

    # Shuffle once, deterministically, so anomalies are interleaved with
    # normals the way they'd arrive in a real stream (not test-then-normal
    # blocks, which would let the baseline "reset" between blocks).
    order = np.random.default_rng(EVAL_SEED + 2).permutation(len(X_test))
    X_test, y_test, crit_test = X_test[order], y_test[order], crit_test[order]

    pids = make_virtual_patients(N_VIRTUAL_PATIENTS)

    # Calibration: pure-normal readings per patient to seed a real baseline.
    for pid in pids:
        calib = np.column_stack([
            rng.normal(75, 8, N_CALIBRATION), rng.normal(97, 1.2, N_CALIBRATION),
            rng.normal(37.0, 0.25, N_CALIBRATION), rng.uniform(0.3, 1.0, N_CALIBRATION),
        ])
        for hr, spo2, temp, mv in calib:
            process_and_store_reading(pid, hr, spo2, temp, mv, source='eval_calibration')

    y_pred_full, y_pred_global, latencies_ms = [], [], []

    for i, (hr, spo2, temp, mv) in enumerate(X_test):
        pid = pids[i % len(pids)]  # round-robin across patients, interleaved stream

        t0 = time.perf_counter()
        result = process_and_store_reading(pid, hr, spo2, temp, mv, source='eval_test')
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        y_pred_full.append(int(result['anomaly']))
        y_pred_global.append(global_only_predict(hr, spo2, temp, mv))

    return {
        'y_true': y_test, 'is_critical': crit_test,
        'y_pred_full': np.array(y_pred_full), 'y_pred_global': np.array(y_pred_global),
        'latencies_ms': np.array(latencies_ms),
    }


# ---------------------------------------------------------------------------
# Real clinical dataset: false alarm rate on true real ICU data
# (all 5 sourced patients are non-septic -> every row is a true negative)
# ---------------------------------------------------------------------------

def run_real_data_false_alarm_check():
    if not os.path.exists(REAL_CSV):
        return None

    with open(REAL_CSV, newline='') as f:
        rows_by_patient = {}
        for row in csv.DictReader(f):
            rows_by_patient.setdefault(row['patient_source_id'], []).append(row)

    flagged, total = 0, 0
    for source_id, rows in rows_by_patient.items():
        conn = get_connection()
        cur = conn.execute(
            "INSERT INTO patients (name, age, health_id, is_demo) VALUES (?, ?, ?, 0)",
            (f"EvalReal-{source_id}", 60, f"EVALREAL-{source_id}")
        )
        pid = cur.lastrowid
        conn.commit()
        conn.close()

        for row in rows:
            result = process_and_store_reading(
                pid, float(row['hr']), float(row['spo2']), float(row['temperature_c']),
                float(row['movement']), source='eval_real',
            )
            total += 1
            flagged += int(result['anomaly'])

    return {'flagged': flagged, 'total': total, 'false_alarm_rate': flagged / total if total else 0.0}


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_metrics(y_true, y_pred, is_critical, label):
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    false_alarm_rate = fp / (fp + tn) if (fp + tn) else 0.0

    crit_mask = (y_true == 1) & (is_critical == 1)
    critical_recall = y_pred[crit_mask].mean() if crit_mask.sum() else float('nan')
    missed_critical_rate = 1 - critical_recall if crit_mask.sum() else float('nan')

    return {
        'label': label,
        'accuracy': accuracy_score(y_true, y_pred),
        'macro_f1': f1_score(y_true, y_pred, average='macro'),
        'recall_sensitivity': recall_score(y_true, y_pred),
        'specificity': specificity,
        'false_alarm_rate': false_alarm_rate,
        'critical_recall': critical_recall,
        'missed_critical_event_rate': missed_critical_rate,
        'confusion_matrix': {'TN': int(tn), 'FP': int(fp), 'FN': int(fn), 'TP': int(tp)},
        'n_critical_cases': int(crit_mask.sum()),
    }


def pct_change(new, old):
    if old == 0 or old != old:  # zero or NaN
        return float('nan')
    return (new - old) / old * 100.0


# ---------------------------------------------------------------------------
# Power consumption: datasheet-based ESTIMATE (no physical hardware available
# in this environment -- needs real bench measurement, e.g. an in-circuit
# INA219, to confirm before being treated as ground truth)
# ---------------------------------------------------------------------------

def power_budget_estimate():
    V = 3.3
    active_ma = 170.0          # ESP32 WiFi TX/RX typical, datasheet range 160-260mA
    sleep_ma = 0.01             # ESP32 deep sleep typical, ~10uA
    read_interval_s = 3.0       # firmware/esp32_vitals_client.ino READ_INTERVAL_MS
    active_window_s = 0.35      # estimated sensor read + WiFi POST round trip

    # As currently shipped: no sleep mode, WiFi stays associated continuously.
    always_on_avg_ma = active_ma

    # Optional duty-cycled design (deep sleep between reads, not yet
    # implemented in the .ino sketch -- would need WiFi reconnect logic).
    duty_cycle = active_window_s / read_interval_s
    duty_cycled_avg_ma = duty_cycle * active_ma + (1 - duty_cycle) * sleep_ma

    def battery_life_hours(avg_ma, capacity_mah):
        return capacity_mah / avg_ma if avg_ma else float('inf')

    return {
        'assumptions': {
            'supply_voltage_v': V,
            'active_current_ma_datasheet_typical': active_ma,
            'deep_sleep_current_ma_datasheet_typical': sleep_ma,
            'read_interval_s': read_interval_s,
            'estimated_active_window_s': active_window_s,
        },
        'as_shipped_always_on': {
            'avg_current_ma': always_on_avg_ma,
            'battery_life_hours_2000mah': battery_life_hours(always_on_avg_ma, 2000),
        },
        'optional_duty_cycled_design': {
            'duty_cycle_pct': duty_cycle * 100,
            'avg_current_ma': duty_cycled_avg_ma,
            'battery_life_hours_2000mah': battery_life_hours(duty_cycled_avg_ma, 2000),
        },
        'caveat': (
            "ESTIMATE from component datasheets, not a bench measurement -- "
            "no physical ESP32/sensor hardware is available in this build "
            "environment. Validate on real hardware with an in-circuit "
            "current sensor (e.g. INA219) before trusting these numbers."
        ),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def format_metrics_table(m):
    cm = m['confusion_matrix']
    return (
        f"| Metric | Value |\n"
        f"|---|---|\n"
        f"| Accuracy | {m['accuracy']:.4f} |\n"
        f"| Macro F1-score | {m['macro_f1']:.4f} |\n"
        f"| Recall / Sensitivity (overall) | {m['recall_sensitivity']:.4f} |\n"
        f"| Specificity | {m['specificity']:.4f} |\n"
        f"| False Alarm Rate | {m['false_alarm_rate']:.4f} ({m['false_alarm_rate']*100:.2f}%) |\n"
        f"| Critical-risk Recall/Sensitivity | {m['critical_recall']:.4f} "
        f"(n={m['n_critical_cases']} critical cases) |\n"
        f"| Missed Critical Event Rate | {m['missed_critical_event_rate']:.4f} "
        f"({m['missed_critical_event_rate']*100:.2f}%) |\n"
        f"| Confusion Matrix | TN={cm['TN']}  FP={cm['FP']}  FN={cm['FN']}  TP={cm['TP']} |\n"
    )


def main():
    print("Loading trained model...")
    load_model()

    print("Preparing isolated evaluation database...")
    fresh_eval_db()

    print(f"Running full pipeline over {N_PER_CLASS_TEST*2} held-out synthetic "
          f"readings (seed={EVAL_SEED}, different from training seed=42)...")
    _kf.clear()  # fresh Kalman filter state for this eval run
    res = run_full_pipeline_eval()

    full_metrics = compute_metrics(res['y_true'], res['y_pred_full'], res['is_critical'], 'Full system (fusion+baseline+ML)')
    global_metrics = compute_metrics(res['y_true'], res['y_pred_global'], res['is_critical'], 'Global-threshold-only (ablation baseline)')

    lat = res['latencies_ms']
    latency_stats = {
        'mean_ms': float(np.mean(lat)), 'median_ms': float(np.median(lat)),
        'p95_ms': float(np.percentile(lat, 95)), 'max_ms': float(np.max(lat)),
        'n_readings': len(lat),
    }

    print("Running real clinical dataset false-alarm check "
          "(all sourced patients non-septic -> true negatives)...")
    real_check = run_real_data_false_alarm_check()

    power = power_budget_estimate()

    f1_improvement_pct = pct_change(full_metrics['macro_f1'], global_metrics['macro_f1'])
    crit_recall_improvement_pct = pct_change(full_metrics['critical_recall'], global_metrics['critical_recall'])
    far_reduction_pct = pct_change(global_metrics['false_alarm_rate'], full_metrics['false_alarm_rate'])

    # -- Console + Markdown report --------------------------------------------------
    lines = []
    lines.append("# Evaluation Report -- Smart Health Risk Alert System\n")
    lines.append(f"Synthetic test set: {N_PER_CLASS_TEST*2} readings "
                 f"({N_PER_CLASS_TEST} normal / {N_PER_CLASS_TEST} anomaly), "
                 f"seed={EVAL_SEED} (held out -- training used seed=42).\n")

    lines.append("\n## 1. Full system (fusion + personalized baseline + ML)\n")
    lines.append(format_metrics_table(full_metrics))

    lines.append("\n## 2. Ablation baseline -- global thresholds only, no personalization/fusion/ML\n")
    lines.append(format_metrics_table(global_metrics))

    lines.append("\n## 3. Personalization/Fusion improvement (%)\n")
    lines.append(
        f"| Comparison | Improvement |\n|---|---|\n"
        f"| Macro F1: full vs. global-only | {f1_improvement_pct:+.1f}% |\n"
        f"| Critical-risk Recall: full vs. global-only | {crit_recall_improvement_pct:+.1f}% |\n"
        f"| False Alarm Rate reduction: full vs. global-only | {far_reduction_pct:+.1f}% |\n"
    )

    lines.append("\n## 4. Real clinical dataset -- false alarm check\n")
    if real_check:
        lines.append(
            f"{real_check['total']} real ICU readings (5 patients, all non-septic "
            f"-> all true negatives, see data/README.md). "
            f"{real_check['flagged']} flagged as anomalous.\n\n"
            f"**Real-world False Alarm Rate: {real_check['false_alarm_rate']*100:.2f}%**\n\n"
            f"_Note: this sample contains no positive/critical cases, so real-world "
            f"Recall/Sensitivity and Critical-risk Recall cannot be measured from it -- "
            f"only synthetic data (Section 1) provides those, since it's the only "
            f"labeled anomaly ground truth available._\n"
        )
    else:
        lines.append("data/clinical_dataset.csv not found -- skipped.\n")

    lines.append("\n## 5. End-to-End Alert Latency (compute pipeline)\n")
    lines.append(
        f"Measured across {latency_stats['n_readings']} calls to "
        f"`process_and_store_reading()` (Kalman filter + baseline read/update "
        f"+ ML predict + fusion + DB write) -- the full decision path from a "
        f"raw reading arriving to a scored, persisted alert.\n\n"
        f"| Statistic | Latency |\n|---|---|\n"
        f"| Mean | {latency_stats['mean_ms']:.2f} ms |\n"
        f"| Median | {latency_stats['median_ms']:.2f} ms |\n"
        f"| p95 | {latency_stats['p95_ms']:.2f} ms |\n"
        f"| Max | {latency_stats['max_ms']:.2f} ms |\n\n"
        f"_This is compute-pipeline latency only. It does NOT include real "
        f"network transmission time from an actual ESP32/Arduino board over "
        f"WiFi/serial -- that requires physical hardware to measure and isn't "
        f"available in this build environment._\n"
    )

    lines.append("\n## 6. Power Consumption (datasheet ESTIMATE, not measured)\n")
    a = power['assumptions']
    s = power['as_shipped_always_on']
    d = power['optional_duty_cycled_design']
    lines.append(
        f"Assumptions: {a['supply_voltage_v']}V supply, "
        f"{a['active_current_ma_datasheet_typical']}mA active (ESP32 WiFi TX/RX, "
        f"datasheet typical), {a['deep_sleep_current_ma_datasheet_typical']}mA deep "
        f"sleep, {a['read_interval_s']}s read interval, "
        f"{a['estimated_active_window_s']}s estimated active window per reading.\n\n"
        f"| Configuration | Avg. current | Est. battery life (2000mAh) |\n|---|---|---|\n"
        f"| As shipped (firmware/esp32_vitals_client.ino, always-on, no sleep) | "
        f"{s['avg_current_ma']:.1f} mA | {s['battery_life_hours_2000mah']:.1f} h "
        f"(~{s['battery_life_hours_2000mah']/24:.1f} days) |\n"
        f"| Optional duty-cycled redesign (deep sleep between reads, not yet "
        f"implemented) | {d['avg_current_ma']:.2f} mA "
        f"({d['duty_cycle_pct']:.1f}% duty cycle) | "
        f"{d['battery_life_hours_2000mah']:.1f} h "
        f"(~{d['battery_life_hours_2000mah']/24:.1f} days) |\n\n"
        f"**{power['caveat']}**\n"
    )

    report = "\n".join(lines)
    print("\n" + report)

    with open(REPORT_PATH, 'w') as f:
        f.write(report)
    print(f"\nWritten to {REPORT_PATH}")

    with open(os.path.join(os.path.dirname(__file__), 'evaluation_report.json'), 'w') as f:
        json.dump({
            'full_system': full_metrics, 'global_only_ablation': global_metrics,
            'improvement_pct': {
                'macro_f1': f1_improvement_pct,
                'critical_recall': crit_recall_improvement_pct,
                'false_alarm_rate_reduction': far_reduction_pct,
            },
            'real_data_false_alarm_check': real_check,
            'latency_ms': latency_stats,
            'power_estimate': power,
        }, f, indent=2, default=float)

    shutil.rmtree(EVAL_DB_DIR, ignore_errors=True)


if __name__ == '__main__':
    main()
