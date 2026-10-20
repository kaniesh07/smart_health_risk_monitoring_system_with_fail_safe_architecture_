# Smart Health Risk Alert System

An edge-AI-style patient monitoring system: a Flask backend scores
heart rate / SpO2 / temperature / movement readings in real time
(Kalman filtering -> adaptive per-patient baseline -> ML classifier ->
multi-signal fusion -> tiered alerting), and a Streamlit dashboard
visualises it.

## What changed from the original version

1. **Real clinical dataset, not a random-number simulator.** The
   dashboard's default view is now backed by real ICU vitals from the
   PhysioNet/CinC 2019 Challenge (see `data/README.md` for the full
   citation and methodology). It's seeded into the database
   automatically the first time the backend boots.
2. **Dual-mode dashboard.**
   - **Default (no hardware connected):** shows the real clinical
     dataset, clearly labelled `📊 DEMO -- Clinical Dataset`.
   - **Live (a controller board is streaming):** the moment an
     Arduino / ESP32 / STM32 board POSTs a reading to `/api/vitals`,
     the dashboard auto-switches to `🔴 LIVE -- streaming from
     <device>` and follows that patient's feed in real time. If the
     board goes quiet for 20 seconds, it automatically falls back to
     the clinical-dataset default -- no manual switching required.
3. **Fixed the backend package** so `python -m backend.app` and
   `gunicorn backend.app:app` (per the `procfile`) both actually work
   (relative imports, `__init__.py` files, a module-level `app`
   object).
4. **Fixed `requirements.txt`** (was missing `plotly` and `gunicorn`)
   and the file layout to match what's actually imported.
5. **Deployment-ready.** Environment-based config, optional API-key auth,
   Docker / Compose / Render / Procfile setups, input validation, health
   probe, pinned dependencies and tests -- see [Deployment](#deployment).

## Project layout

```
backend/            Flask API: ingestion, scoring, alerting, DB
  app.py              App factory + boot sequence (seeds clinical data)
  config.py           Environment-variable settings (API_KEY, DB path, ...)
  routes.py           /api/... endpoints, incl. /api/live_status
  ingest.py           Shared scoring pipeline (used by live + seed data)
  alert_engine.py     Multi-signal fusion + tiered alert levels
  model.py            Loads/serves the trained ML classifier
  database.py         SQLite schema + migrations
  utils.py            Kalman filter, running stats

dashboard/app.py    Streamlit UI -- default/live auto-switching lives here

data/
  clinical_dataset.csv   Real ICU vitals (see data/README.md)
  seed_clinical_data.py  Loads the CSV into the DB on first boot

ml/train_model.py   Trains the anomaly classifier, sanity-checks vs. real data

firmware/
  esp32_vitals_client.ino   Example WiFi board firmware (ESP32/Arduino+WiFi)
  serial_bridge.py          For boards without WiFi (plain Arduino/STM32, USB)

simulator/replay_clinical.py   Optional: replay real data as a fake LIVE
                                 stream for testing without hardware

tests/              API smoke tests (pytest)

Dockerfile, docker-compose.yml, render.yaml, Procfile, gunicorn.conf.py,
.streamlit/config.toml, .env.example     Deployment configuration
```

## Evaluation

`python -m ml.evaluate` runs the full detection pipeline (not just the
raw classifier) against a held-out synthetic test set, the real
clinical dataset, and a naive global-threshold-only ablation baseline
-- writing `ml/evaluation_report.md` + `.json`. Headline results from
the last run:

| Metric | Full system | Global-only (no fusion/baseline/ML) |
|---|---|---|
| Accuracy | 0.9600 | 0.9400 |
| Macro F1 | 0.9599 | 0.9398 |
| Recall/Sensitivity | 0.9233 | 0.8800 |
| Specificity | 0.9967 | 1.0000 |
| Critical-risk Recall | **1.0000** | 0.9422 |
| Missed Critical Event Rate | **0.00%** | 5.78% |
| False Alarm Rate (synthetic) | 0.33% | 0.00% |

- **Personalization + fusion catches every critical/red-flag case** in
  the test set (100% critical recall vs. 94.2% for bare thresholds) at
  the cost of one extra false positive out of 300 normal readings --
  a real, honest tradeoff, not spun as a pure win.
- **Real-world false alarm rate is 20.89%** on the actual PhysioNet
  ICU data -- notably higher than the 0.33% synthetic figure. Real
  patients have more physiological variability than clean synthetic
  Gaussians; this gap is a genuine limitation, not a bug, and is the
  clearest sign the synthetic training data doesn't fully cover
  real-world variance.
- End-to-end compute latency: 1.73ms mean / 1.96ms p95 per reading
  (pipeline only -- excludes real board network time, not measurable
  without physical hardware).
- Power consumption is a **datasheet-based estimate only** (no
  physical ESP32 available to bench-measure) -- see the full report
  for the always-on vs. duty-cycled comparison.

Full breakdown, confusion matrices, and methodology notes are in
`ml/evaluation_report.md`.

## Running it

```bash
pip install -r requirements.txt      # Python 3.13 recommended (see .python-version)

# 1. (Optional) retrain the ML model -- ml/model.pkl + ml/scaler.pkl are
#    committed, and the backend trains them itself if they're missing
python -m ml.train_model

# 2. Start the backend (also seeds the real clinical dataset on first run)
python -m backend.app          # http://localhost:5000

# 3. In a second terminal, start the dashboard
streamlit run dashboard/app.py  # http://localhost:8501
```

Open the dashboard -- it will already be showing real ICU patient data
(`📊 DEMO -- Clinical Dataset`) with no further setup.

### Connecting a real controller board

- **ESP32 / Arduino with WiFi:** flash `firmware/esp32_vitals_client.ino`
  (fill in your WiFi credentials and backend LAN IP), wire up your
  actual sensors in place of the placeholder `read*()` functions. As
  soon as it starts POSTing, the dashboard switches to LIVE mode
  automatically.
- **Plain Arduino Uno / STM32 (USB serial, no WiFi):** have the board
  print `hr,spo2,temp,movement` as one CSV line per reading over
  serial, then run:
  ```bash
  pip install -r requirements-device.txt
  python -m firmware.serial_bridge --port /dev/ttyUSB0 --patient_id 1
  ```
- **No hardware yet, want to see LIVE mode work:**
  ```bash
  python -m simulator.replay_clinical --patient_source p000998
  ```
  This replays real recorded readings as if a device were streaming
  them, purely for testing the dashboard's auto-switch behaviour.

## Deployment

The project ships as **two services** built from the same code:

| Service | Start command | Port | Purpose |
|---|---|---|---|
| Backend API | `gunicorn backend.app:app --config gunicorn.conf.py` | `$PORT` (5000) | Devices POST readings here; scoring + alerting + DB |
| Dashboard | `streamlit run dashboard/app.py --server.port $PORT --server.address 0.0.0.0` | `$PORT` (8501) | Streamlit UI; talks to the backend over HTTP |

### Configuration (environment variables)

| Variable | Service | Default | Notes |
|---|---|---|---|
| `API_KEY` | both | *(unset = no auth)* | Shared secret. When set, every `/api/*` call needs an `X-API-Key` header. **Set this for any public deploy.** |
| `BACKEND_URL` | dashboard, simulator, serial bridge | `http://localhost:5000` | Public URL of the backend |
| `HEALTH_DB_PATH` | backend | `database/health.db` | Point at a persistent disk to keep data across restarts |
| `SEED_DEMO_DATA` | backend | `true` | Load the PhysioNet demo patients into an empty DB on boot |
| `LIVE_TIMEOUT_SECONDS` | backend | `20` | How long a device stays "live" after its last reading |
| `FLASK_DEBUG` | backend | `0` | Local dev only -- never in production |
| `PORT` | both | 5000 / 8501 | Injected automatically by hosting platforms |

See `.env.example`. Generate a key with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### Option A -- Docker Compose (laptop, Raspberry Pi, any VPS)

```bash
cp .env.example .env          # set API_KEY
docker compose up -d --build
```

API on `:5000`, dashboard on `:8501`. The database lives in the
`health-data` volume, so it survives restarts and rebuilds.

### Option B -- Render (free tier, two services)

1. Push the code to your own git repository.
2. In Render: **New + → Blueprint** → pick the repo. `render.yaml` creates
   `health-monitor-api` and `health-monitor-dashboard` and generates an
   `API_KEY` shared by both.
3. When prompted for the dashboard's `BACKEND_URL`, enter the API's public
   URL (e.g. `https://health-monitor-api.onrender.com`). If you don't know
   it yet, deploy, copy it from the API service page, then set it under
   the dashboard's **Environment** tab.
4. Read the generated `API_KEY` from the API service's Environment tab --
   your ESP32 / serial bridge / simulator need it.

Free-tier caveats: services sleep after ~15 min idle (first request takes
~30-60 s; the dashboard waits and retries), and there is no persistent
disk, so the database is rebuilt and reseeded on every restart. For
persistent live data, use a paid plan with a disk mounted at `/var/data`
and set `HEALTH_DB_PATH=/var/data/health.db` (commented in `render.yaml`).

### Option C -- Heroku / Railway / other Procfile hosts

The `Procfile` runs the backend. Deploy the dashboard as a second app/service
from the same repo with the Streamlit start command above, and set
`BACKEND_URL` + `API_KEY` on it.

### Pointing devices at a deployed backend

- **ESP32:** in `firmware/esp32_vitals_client.ino` set
  `BACKEND_URL = "https://<your-api>/api/vitals"` and `API_KEY`. HTTPS is
  handled automatically.
- **Serial bridge:** `pip install -r requirements-device.txt`, then
  `python -m firmware.serial_bridge --port COM5 --patient_id 1 --api_url https://<your-api> --api_key <key>`
- **Simulator:** `python -m simulator.replay_clinical --api_url https://<your-api> --api_key <key>`

### Production notes

- The API runs as **one gunicorn worker with 4 threads** on purpose: the
  per-patient Kalman filters live in process memory, so all readings for a
  patient must reach the same process. SQLite runs in WAL mode with a busy
  timeout so concurrent reads/writes don't fail.
- `GET /healthz` is an unauthenticated health probe (used by Docker and
  Render). All other endpoints return JSON errors (400 / 401 / 404 / 500),
  never HTML.
- `POST /api/vitals` now validates input: non-numeric values → 400,
  unknown `patient_id` → 404 (create the patient first with
  `POST /api/patient`).
- `ml/model.pkl` / `scaler.pkl` are committed. If they're missing, the
  backend trains them on boot (deterministic, ~1 s); the Docker image
  always retrains at build time so the pickle matches the installed
  scikit-learn.

### Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```


## Alerting tiers

| Level | Trigger                          | Action (as designed)   |
|-------|-----------------------------------|--------------------------|
| 0     | Normal                            | --                        |
| 1     | Mild -- 1 signal deviates          | Local buzzer               |
| 2     | Moderate -- score >= 0.60 or 2 signals | SMS via GSM/2G module  |
| 3     | Critical -- score >= 0.85 or 3+ signals | Push notification (cloud) |
