"""
simulator/replay_clinical.py
-----------------------------
NOT the dashboard's data source anymore -- that's the real clinical
dataset, seeded once at boot (see data/seed_clinical_data.py).

This script is only a *testing convenience*: it replays real clinical-
dataset rows over HTTP to POST /api/vitals tagged as source='live_device',
so you can see the dashboard's LIVE mode (banner, auto-switch, live_status)
work end-to-end before you have real Arduino/ESP32/STM32 hardware wired up.

Usage (from project root, with the backend running):
    python -m simulator.replay_clinical --patient_source p000998 --interval 2

--patient_source : which demo patient's real readings to replay
                    (see data/clinical_dataset.csv patient_source_id column)
--interval        : seconds between readings (default 3)
--device_id        : label sent with each reading (default "SIM-REPLAY-01")
--api_url          : backend base URL (default $BACKEND_URL or http://localhost:5000)
--api_key          : sent as X-API-Key (default $API_KEY)

Against a deployed backend:
    python -m simulator.replay_clinical --api_url https://your-backend.onrender.com --api_key <key>
"""
import argparse
import csv
import os
import time

import requests

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'clinical_dataset.csv')
API_URL = None            # set in main()
SESSION = requests.Session()


def _api_base(url: str) -> str:
    url = url.rstrip('/')
    return url if url.endswith('/api') else url + '/api'


def find_patient_id(source_id: str):
    r = SESSION.get(f"{API_URL}/patients", timeout=60)
    r.raise_for_status()
    patients = r.json()
    for p in patients:
        if p.get('health_id') == f"DEMO-{source_id}":
            return p['id']
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--patient_source', default='p000998',
                         help="patient_source_id from clinical_dataset.csv")
    parser.add_argument('--interval', type=float, default=3.0)
    parser.add_argument('--device_id', default='SIM-REPLAY-01')
    parser.add_argument('--api_url', default=os.environ.get('BACKEND_URL', 'http://localhost:5000'))
    parser.add_argument('--api_key', default=os.environ.get('API_KEY', ''))
    args = parser.parse_args()

    global API_URL
    API_URL = _api_base(args.api_url)
    if args.api_key:
        SESSION.headers['X-API-Key'] = args.api_key

    patient_id = find_patient_id(args.patient_source)
    if patient_id is None:
        print(f"No seeded demo patient found for '{args.patient_source}'. "
              f"Make sure the backend has booted (and seeded) at least once.")
        return

    with open(CSV_PATH, newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['patient_source_id'] == args.patient_source]

    print(f"Replaying {len(rows)} real readings for patient_id={patient_id} "
          f"every {args.interval}s as a LIVE device stream ('{args.device_id}')...")

    for row in rows:
        payload = {
            'patient_id': patient_id,
            'hr': float(row['hr']),
            'spo2': float(row['spo2']),
            'temperature': float(row['temperature_c']),
            'movement': float(row['movement']),
            'source': 'live_device',
            'device_id': args.device_id,
        }
        try:
            r = SESSION.post(f"{API_URL}/vitals", json=payload, timeout=30)
            result = r.json()
            print(f"  HR={payload['hr']:.0f} SpO2={payload['spo2']:.0f} "
                  f"Temp={payload['temperature']:.1f}  -> "
                  f"alert_level={result.get('alert_level')}")
        except Exception as exc:
            print(f"  POST failed: {exc}")
        time.sleep(args.interval)

    print("Replay finished. The dashboard will fall back to the default "
          "clinical-dataset view ~20s after the last reading.")


if __name__ == '__main__':
    main()
