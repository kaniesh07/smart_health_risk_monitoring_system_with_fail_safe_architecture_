# Evaluation Report -- Smart Health Risk Alert System

Synthetic test set: 600 readings (300 normal / 300 anomaly), seed=123 (held out -- training used seed=42).


## 1. Full system (fusion + personalized baseline + ML)

| Metric | Value |
|---|---|
| Accuracy | 0.9600 |
| Macro F1-score | 0.9599 |
| Recall / Sensitivity (overall) | 0.9233 |
| Specificity | 0.9967 |
| False Alarm Rate | 0.0033 (0.33%) |
| Critical-risk Recall/Sensitivity | 1.0000 (n=225 critical cases) |
| Missed Critical Event Rate | 0.0000 (0.00%) |
| Confusion Matrix | TN=299  FP=1  FN=23  TP=277 |


## 2. Ablation baseline -- global thresholds only, no personalization/fusion/ML

| Metric | Value |
|---|---|
| Accuracy | 0.9400 |
| Macro F1-score | 0.9398 |
| Recall / Sensitivity (overall) | 0.8800 |
| Specificity | 1.0000 |
| False Alarm Rate | 0.0000 (0.00%) |
| Critical-risk Recall/Sensitivity | 0.9422 (n=225 critical cases) |
| Missed Critical Event Rate | 0.0578 (5.78%) |
| Confusion Matrix | TN=300  FP=0  FN=36  TP=264 |


## 3. Personalization/Fusion improvement (%)

| Comparison | Improvement |
|---|---|
| Macro F1: full vs. global-only | +2.1% |
| Critical-risk Recall: full vs. global-only | +6.1% |
| False Alarm Rate reduction: full vs. global-only | -100.0% |


## 4. Real clinical dataset -- false alarm check

158 real ICU readings (5 patients, all non-septic -> all true negatives, see data/README.md). 33 flagged as anomalous.

**Real-world False Alarm Rate: 20.89%**

_Note: this sample contains no positive/critical cases, so real-world Recall/Sensitivity and Critical-risk Recall cannot be measured from it -- only synthetic data (Section 1) provides those, since it's the only labeled anomaly ground truth available._


## 5. End-to-End Alert Latency (compute pipeline)

Measured across 600 calls to `process_and_store_reading()` (Kalman filter + baseline read/update + ML predict + fusion + DB write) -- the full decision path from a raw reading arriving to a scored, persisted alert.

| Statistic | Latency |
|---|---|
| Mean | 16.53 ms |
| Median | 15.89 ms |
| p95 | 19.99 ms |
| Max | 65.32 ms |

_This is compute-pipeline latency only. It does NOT include real network transmission time from an actual ESP32/Arduino board over WiFi/serial -- that requires physical hardware to measure and isn't available in this build environment._


## 6. Power Consumption (datasheet ESTIMATE, not measured)

Assumptions: 3.3V supply, 170.0mA active (ESP32 WiFi TX/RX, datasheet typical), 0.01mA deep sleep, 3.0s read interval, 0.35s estimated active window per reading.

| Configuration | Avg. current | Est. battery life (2000mAh) |
|---|---|---|
| As shipped (firmware/esp32_vitals_client.ino, always-on, no sleep) | 170.0 mA | 11.8 h (~0.5 days) |
| Optional duty-cycled redesign (deep sleep between reads, not yet implemented) | 19.84 mA (11.7% duty cycle) | 100.8 h (~4.2 days) |

**ESTIMATE from component datasheets, not a bench measurement -- no physical ESP32/sensor hardware is available in this build environment. Validate on real hardware with an in-circuit current sensor (e.g. INA219) before trusting these numbers.**
