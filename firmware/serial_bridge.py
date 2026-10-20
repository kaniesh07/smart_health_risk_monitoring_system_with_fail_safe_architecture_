"""
firmware/serial_bridge.py
---------------------------
For controller boards WITHOUT WiFi (a plain Arduino Uno/Nano, or an STM32
Nucleo/Blue Pill on USB serial) -- these can't POST HTTP directly, so this
bridge script runs on the same PC/Raspberry Pi as the backend, reads
sensor lines the board prints over USB serial, and forwards them to
POST /api/vitals tagged source="live_device".

Expected line format from the board (one CSV line per reading), e.g. from
a bare-metal Arduino sketch doing:

    Serial.print(hr);   Serial.print(",");
    Serial.print(spo2); Serial.print(",");
    Serial.print(temp); Serial.print(",");
    Serial.println(movement);

  ->  "78.5,97.2,36.9,0.42"

Usage:
    python -m firmware.serial_bridge --port /dev/ttyUSB0 --patient_id 1 \
        --device_id ARDUINO-ICU-02

On Windows, --port is something like COM5.

To forward to a deployed (cloud) backend instead of localhost:
    python -m firmware.serial_bridge --port COM5 --patient_id 1 \
        --api_url https://your-backend.onrender.com --api_key <key>
(or set the BACKEND_URL / API_KEY environment variables).
"""
import argparse
import os
import time

import requests
import serial  # pip install pyserial



def _vitals_url(base: str) -> str:
    base = base.rstrip('/')
    if base.endswith('/api/vitals'):
        return base
    return (base if base.endswith('/api') else base + '/api') + '/vitals'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True, help="Serial port, e.g. /dev/ttyUSB0 or COM5")
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--patient_id', type=int, required=True)
    parser.add_argument('--device_id', default='SERIAL-BOARD-01')
    parser.add_argument('--api_url', default=os.environ.get('BACKEND_URL', 'http://localhost:5000'))
    parser.add_argument('--api_key', default=os.environ.get('API_KEY', ''))
    args = parser.parse_args()

    api_url = _vitals_url(args.api_url)
    session = requests.Session()
    if args.api_key:
        session.headers['X-API-Key'] = args.api_key

    ser = serial.Serial(args.port, args.baud, timeout=2)
    print(f"Listening on {args.port} @ {args.baud} baud for patient_id={args.patient_id} "
          f"-> {api_url}")
    time.sleep(2)  # allow board to reset after serial connection opens

    while True:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            parts = line.split(',')
            if len(parts) < 4:
                print(f"Skipping malformed line: {line!r}")
                continue

            hr, spo2, temp, movement = (float(p) for p in parts[:4])
            payload = {
                'patient_id': args.patient_id,
                'hr': hr, 'spo2': spo2, 'temperature': temp, 'movement': movement,
                'source': 'live_device',
                'device_id': args.device_id,
            }
            r = session.post(api_url, json=payload, timeout=30)
            print(f"  {line} -> alert_level={r.json().get('alert_level')}")

        except ValueError:
            print(f"Could not parse line: {line!r}")
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as exc:
            print(f"Error: {exc}")
            time.sleep(1)


if __name__ == '__main__':
    main()
