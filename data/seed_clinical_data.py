"""
data/seed_clinical_data.py
---------------------------
Loads clinical_dataset.csv (real ICU vitals sampled from the PhysioNet /
Computing in Cardiology Challenge 2019 "Early Prediction of Sepsis from
Clinical Data" open dataset -- see data/README.md for the citation and
methodology) into the app's database, replacing the old random-number
`simulate.py` generator as the source of the *default* dashboard view.

Runs automatically once, on first boot, from backend/app.py. Can also be
run standalone:

    python -m data.seed_clinical_data
"""
import os
import csv
from collections import defaultdict

from backend.database import get_connection, init_db
from backend.ingest import process_and_store_reading

CSV_PATH = os.path.join(os.path.dirname(__file__), 'clinical_dataset.csv')


def seed():
    if not os.path.exists(CSV_PATH):
        print(f"[SEED] clinical_dataset.csv not found at {CSV_PATH}, skipping.")
        return

    init_db()
    conn = get_connection()
    existing = conn.execute('SELECT COUNT(*) AS n FROM patients').fetchone()['n']
    if existing > 0:
        conn.close()
        print("[SEED] Patients already present -- skipping clinical dataset seed.")
        return

    # Group CSV rows by patient, preserving arrival order (already sorted by
    # timestamp in the CSV).
    rows_by_patient = defaultdict(list)
    with open(CSV_PATH, newline='') as f:
        for row in csv.DictReader(f):
            rows_by_patient[row['patient_source_id']].append(row)

    for source_id, rows in rows_by_patient.items():
        first = rows[0]
        cur = conn.execute(
            'INSERT INTO patients (name, age, health_id, is_demo) VALUES (?, ?, ?, 1)',
            (first['patient_name'], int(first['age']), f"DEMO-{source_id}")
        )
        patient_id = cur.lastrowid
        conn.commit()

        for row in rows:
            process_and_store_reading(
                patient_id=patient_id,
                hr=float(row['hr']),
                spo2=float(row['spo2']),
                temperature=float(row['temperature_c']),
                movement=float(row['movement']),
                source='clinical_dataset',
                device_id=None,
                timestamp=row['timestamp'],
            )

        print(f"[SEED] Loaded {len(rows)} real vitals readings for "
              f"'{first['patient_name']}' (patient_id={patient_id}).")

    conn.close()
    print(f"[SEED] Done -- {len(rows_by_patient)} demo patients loaded from "
          f"the real PhysioNet clinical dataset.")


if __name__ == '__main__':
    seed()
