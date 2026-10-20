"""
dashboard/app.py
-----------------
Streamlit monitoring dashboard.

Behaviour (this is the piece that satisfies "default dashboard visible at
open, live dashboard when a controller board is streaming"):

  * On open (and on every auto-refresh) it polls GET /api/live_status.
  * If NO Arduino / ESP32 / STM32 board has posted a reading in the last
    LIVE_TIMEOUT_SECONDS -> shows the DEFAULT view: the real clinical
    dataset (PhysioNet ICU vitals) seeded at boot, clearly labelled
    "DEMO -- Clinical Dataset".
  * The moment a board POSTs to /api/vitals with source=live_device (or
    the default, since that's the endpoint's default source) -> the
    dashboard auto-switches to that patient's feed and shows a
    "LIVE -- Streaming from <device>" banner, refreshing continuously.
  * If the board goes quiet for LIVE_TIMEOUT_SECONDS, it reverts back to
    the default clinical-dataset view automatically.
  * A sidebar toggle lets the user "pin" a patient and browse the demo
    dataset manually even while a device could be live.

Run from project root:
    streamlit run dashboard/app.py

Configuration (environment variables):
    BACKEND_URL   Base URL of the Flask backend   (default http://localhost:5000)
    API_KEY       Sent as X-API-Key if the backend requires one
"""
import os
import time

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:5000").rstrip("/")
if not BACKEND_URL.startswith(("http://", "https://")):
    BACKEND_URL = "https://" + BACKEND_URL   # allow bare hostnames from hosting dashboards
BASE_URL = BACKEND_URL[:-4] if BACKEND_URL.endswith("/api") else BACKEND_URL
BASE_URL = f"{BASE_URL}/api"

API_KEY = os.environ.get("API_KEY", "").strip()
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

# Free hosting tiers put idle services to sleep; the first request after a
# nap can take ~30-60 s, so be patient with it.
TIMEOUT = float(os.environ.get("BACKEND_TIMEOUT", "10"))

st.set_page_config(
    page_title="Smart Health Monitor",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

ALERT_COLOR = {0: '🟢', 1: '🟡', 2: '🟠', 3: '🔴'}
ALERT_LABEL = {0: 'Normal', 1: 'Mild (Buzzer)', 2: 'Moderate (SMS)', 3: 'Critical (Push)'}


# -- API helpers ----------------------------------------------------------------

@st.cache_resource
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def api_get(path: str, default=None):
    try:
        r = _session().get(f"{BASE_URL}{path}", timeout=TIMEOUT)
        return r.json() if r.ok else default
    except Exception:
        return default


def api_post(path: str, body: dict):
    try:
        r = _session().post(f"{BASE_URL}{path}", json=body, timeout=TIMEOUT)
        return r.json() if r.ok else {"error": r.json().get("error", r.reason)}
    except Exception as exc:
        return {"error": str(exc)}


def backend_status():
    """Returns (ok: bool, message: str) for the backend connection."""
    try:
        r = _session().get(f"{BASE_URL}/live_status", timeout=max(TIMEOUT, 60))
    except requests.exceptions.RequestException as exc:
        return False, f"Cannot reach the backend at `{BACKEND_URL}` ({type(exc).__name__})."
    if r.status_code == 401:
        return False, ("The backend rejected the API key. Set the same `API_KEY` "
                       "on the dashboard as on the backend.")
    if not r.ok:
        return False, f"Backend at `{BACKEND_URL}` answered HTTP {r.status_code}."
    return True, ""


# -- Backend connectivity check --------------------------------------------------

_ok, _msg = backend_status()
if not _ok:
    st.error(f"⚠ {_msg}")
    st.caption("Check that the backend service is running and that this "
               "dashboard's `BACKEND_URL` / `API_KEY` environment variables "
               "point at it. Retrying automatically…")
    time.sleep(5)
    st.rerun()


# -- Live vs. default (clinical-dataset) mode resolution -------------------------

live_status = api_get('/live_status', {'live': False}) or {'live': False}
is_live = bool(live_status.get('live'))
live_patient_id = live_status.get('patient_id')
live_device_id = live_status.get('device_id')


# -- Sidebar ----------------------------------------------------------------------

with st.sidebar:
    st.image("https://img.icons8.com/color/96/heart-monitor.png", width=60)
    st.title("Smart Health Monitor")
    st.caption("Edge AI · Offline-First · Multi-Signal Fusion")
    st.divider()

    if is_live:
        st.success(f"🔴 LIVE feed detected\nDevice: {live_device_id or 'unknown'}")
    else:
        st.info("📊 No live device streaming.\nShowing the clinical dataset (demo).")

    follow_live = st.toggle(
        "🔌 Follow live device automatically",
        value=True,
        help="When on, the dashboard auto-switches to whichever patient a "
             "connected Arduino / ESP32 / STM32 board is streaming to. "
             "Turn off to freely browse the clinical dataset instead.",
    )

    st.divider()

    patients = api_get('/patients', [])
    if patients:
        options = {f"{p['name']}  (ID {p['id']})": p['id'] for p in patients}
        ids_list = list(options.values())

        # Decide the default selection for the dropdown.
        if follow_live and is_live and live_patient_id in ids_list:
            default_index = ids_list.index(live_patient_id)
        else:
            # Prefer the first demo (clinical-dataset) patient as the
            # opening default so the dashboard is never empty.
            demo_ids = [p['id'] for p in patients if p.get('is_demo')]
            default_index = ids_list.index(demo_ids[0]) if demo_ids else 0

        sel_label = st.selectbox(
            "👤 Select Patient", list(options.keys()), index=default_index
        )
        pid = options[sel_label]

        # If following live and a device is active, always force that
        # patient regardless of the manual dropdown choice.
        if follow_live and is_live and live_patient_id in ids_list:
            pid = live_patient_id
    else:
        st.warning("No patients yet -- add one below, or wait for the "
                    "clinical dataset to finish seeding.")
        pid = None

    st.divider()
    st.subheader("➕ Add Patient")
    new_name = st.text_input("Name")
    new_age = st.number_input("Age", 1, 120, 65)
    new_hid = st.text_input("ABDM Health ID (optional)")
    if st.button("Register", width="stretch"):
        if new_name:
            res = api_post('/patient', {'name': new_name, 'age': new_age, 'health_id': new_hid})
            if res and 'patient_id' in res:
                st.success(f"Registered! Patient ID: {res.get('patient_id')}")
                st.rerun()
            else:
                st.error(f"Could not register: {(res or {}).get('error', 'unknown error')}")
        else:
            st.error("Name is required.")

    st.divider()
    limit = st.slider("Readings to display", 20, 200, 80)
    refresh_rate = st.slider("Auto-refresh (s)", 2, 30, 4)
    auto_refresh = st.toggle("⟳ Auto-refresh", value=True)


# -- Main ---------------------------------------------------------------------------

if not pid:
    st.info("Register a patient in the sidebar to begin monitoring, or "
            "start the backend so the clinical dataset can seed itself.")
    st.stop()

# Mode banner
if follow_live and is_live and pid == live_patient_id:
    st.markdown(
        f"### 🔴 LIVE -- streaming from `{live_device_id or 'controller board'}`"
    )
else:
    st.markdown("### 📊 DEMO -- Clinical Dataset (PhysioNet 2019 Challenge, real ICU vitals)")

vitals_raw = api_get(f'/vitals/{pid}?limit={limit}', [])
baseline = api_get(f'/baseline/{pid}')

if not vitals_raw:
    st.warning(
        "No vitals data for this patient yet. If this is a live device "
        "patient, waiting for its first reading at POST /api/vitals."
    )
    st.stop()

df = pd.DataFrame(vitals_raw)
# format='ISO8601': seeded rows have no microseconds, live rows do.
df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601')
df = df.sort_values('timestamp').reset_index(drop=True)
latest = df.iloc[-1]

# -- Alert banner ------------------------------------------------------------------
lvl = int(latest['alert_level'])
if lvl == 3:
    st.error(f"🚨 CRITICAL ALERT -- Immediate attention required!  (Score: {latest['anomaly_score']:.2f})")
elif lvl == 2:
    st.warning(f"📱 MODERATE ALERT -- SMS dispatched to caregiver.  (Score: {latest['anomaly_score']:.2f})")
elif lvl == 1:
    st.info(f"🔔 MILD ALERT -- Local buzzer triggered.  (Score: {latest['anomaly_score']:.2f})")

# -- KPI row -------------------------------------------------------------------------
st.subheader("📊 Latest Reading")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Heart Rate", f"{latest['hr']:.1f} bpm",
          "Normal" if 60 <= latest['hr'] <= 100 else "⚠ Abnormal")
c2.metric("SpO₂", f"{latest['spo2']:.1f} %",
          "Normal" if latest['spo2'] >= 95 else "⚠ Low")
c3.metric("Temperature", f"{latest['temperature']:.2f} °C",
          "Normal" if 36 <= latest['temperature'] <= 37.5 else "⚠ Abnormal")
c4.metric("Movement", f"{latest['movement']:.2f}",
          "Active" if latest['movement'] > 0.1 else "⚠ Immobile")
c5.metric("Alert Level", f"{ALERT_COLOR[lvl]} {ALERT_LABEL[lvl]}")

st.caption(f"Data source: `{latest.get('source', 'unknown')}`" +
           (f" · device `{latest.get('device_id')}`" if latest.get('device_id') else ""))

st.divider()

# -- Charts --------------------------------------------------------------------------
st.subheader("📈 Vitals Trends")
tab_hr, tab_spo2, tab_temp, tab_score = st.tabs(
    ["Heart Rate", "SpO₂", "Temperature", "Anomaly Score"]
)

anomalies = df[df['is_anomaly'] == 1]


def anomaly_markers(y_col, color='red'):
    return go.Scatter(
        x=anomalies['timestamp'], y=anomalies[y_col],
        mode='markers', name='Anomaly',
        marker=dict(color=color, size=9, symbol='x', line=dict(width=2)),
    )


with tab_hr:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['hr'],
                              name='HR', line=dict(color='#FF6B6B', width=2)))
    if baseline:
        mean, std = baseline.get('hr_mean', 75), baseline.get('hr_std', 10)
        fig.add_hrect(y0=mean - 2.5 * std, y1=mean + 2.5 * std,
                      fillcolor='rgba(255,107,107,0.08)', line_width=0,
                      annotation_text='Personal range', annotation_position='top left')
    fig.add_trace(anomaly_markers('hr'))
    fig.update_layout(yaxis_title='bpm', height=320, showlegend=True,
                       legend=dict(orientation='h'))
    st.plotly_chart(fig, width="stretch")

with tab_spo2:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['spo2'],
                              name='SpO₂', line=dict(color='#4ECDC4', width=2)))
    fig.add_hline(y=95, line_dash='dash', line_color='orange',
                  annotation_text='Min safe SpO₂ 95%')
    fig.add_trace(anomaly_markers('spo2', '#4ECDC4'))
    fig.update_layout(yaxis_title='%', yaxis_range=[80, 101], height=320)
    st.plotly_chart(fig, width="stretch")

with tab_temp:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['temperature'],
                              name='Temp', line=dict(color='#FFE66D', width=2)))
    fig.add_hrect(y0=36.0, y1=37.5, fillcolor='rgba(255,230,109,0.1)',
                  line_width=0, annotation_text='Normal range')
    fig.add_trace(anomaly_markers('temperature', '#FFE66D'))
    fig.update_layout(yaxis_title='°C', height=320)
    st.plotly_chart(fig, width="stretch")

with tab_score:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['anomaly_score'],
                              name='Score', fill='tozeroy',
                              line=dict(color='#FF6B6B', width=1.5)))
    fig.add_hline(y=0.60, line_dash='dash', line_color='orange',
                  annotation_text='Moderate threshold')
    fig.add_hline(y=0.85, line_dash='dash', line_color='red',
                  annotation_text='Critical threshold')
    fig.update_layout(yaxis_title='Score', yaxis_range=[0, 1], height=320)
    st.plotly_chart(fig, width="stretch")

# -- Adaptive baseline card -----------------------------------------------------------
if baseline:
    st.divider()
    st.subheader("📐 Adaptive Personal Baseline")
    n = baseline.get('reading_count', 0)
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric("HR", f"{baseline['hr_mean']:.1f} ± {baseline['hr_std']:.1f} bpm")
    bc2.metric("SpO₂", f"{baseline['spo2_mean']:.1f} ± {baseline['spo2_std']:.1f} %")
    bc3.metric("Temp", f"{baseline['temp_mean']:.2f} ± {baseline['temp_std']:.2f} °C")
    bc4.metric("Readings", n)
    if n < 10:
        st.progress(n / 10, text=f"Collecting baseline… {n}/10 readings")

# -- Recent anomalies table ------------------------------------------------------------
st.divider()
st.subheader("🚨 Recent Anomalies")
adf = df[df['is_anomaly'] == 1][
    ['timestamp', 'hr', 'spo2', 'temperature', 'movement', 'anomaly_score', 'alert_level']
].tail(10).copy()

if not adf.empty:
    adf['alert_level'] = adf['alert_level'].map(ALERT_COLOR)
    st.dataframe(adf, width="stretch", hide_index=True)
else:
    st.success("No anomalies detected in the current window.")

# -- Stats footer ------------------------------------------------------------------------
st.divider()
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Readings", len(df))
s2.metric("Anomalies", int(df['is_anomaly'].sum()))
rate = df['is_anomaly'].mean() * 100
s3.metric("Anomaly Rate", f"{rate:.1f}%")
s4.metric("Avg Anomaly Score", f"{df['anomaly_score'].mean():.3f}")

# -- Auto-refresh ---------------------------------------------------------------------------
# Re-checks /live_status on every cycle, which is what lets the dashboard
# hop onto a live board's feed the moment it starts streaming, and drop
# back to the clinical-dataset default the moment it goes quiet.
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
