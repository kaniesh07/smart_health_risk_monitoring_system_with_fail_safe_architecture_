# Clinical dataset

`clinical_dataset.csv` replaces the old synthetic random-number
`simulate.py` generator as the source of the dashboard's **default**
view. It contains real ICU bedside-monitor vitals for 5 patients
(158 timestamped readings total), sampled directly from:

> **Reyna, M., Josef, C., Jeter, R., et al.**
> *Early Prediction of Sepsis from Clinical Data: The PhysioNet/Computing
> in Cardiology Challenge 2019.*
> PhysioNet, https://physionet.org/content/challenge-2019/1.0.0/

The Challenge dataset is openly published by PhysioNet / the MIT
Laboratory for Computational Physiology for research and educational
use; see the dataset page above for full terms before any commercial
or clinical use.

## Columns kept

From each patient's original `.psv` file we kept the three vitals this
project's alert engine actually uses, plus identifiers:

| Column           | Source field | Notes                                            |
|------------------|--------------|---------------------------------------------------|
| `hr`             | `HR`         | Heart rate, bpm                                    |
| `spo2`           | `O2Sat`      | Blood oxygen saturation, %                          |
| `temperature_c`  | `Temp`       | Body temperature, degC                              |
| `sepsis_label`   | `SepsisLabel`| Ground-truth clinical label (kept for reference)    |
| `iculos_hour`    | `ICULOS`     | Original hour-in-ICU index                          |
| `age`, `gender`  | `Age`, `Gender` | Patient demographics                             |

## What was NOT real, and why

- **`movement`** -- the PhysioNet ICU dataset has no accelerometer /
  motion channel, so this column is synthesized (low-movement,
  bed-bound ICU pattern) purely so the existing multi-signal fusion
  logic (which expects a movement reading) has something to fuse.
- **`timestamp`** -- the original data is indexed by hour-in-ICU
  (`ICULOS`), not wall-clock time. Timestamps were re-spaced to
  3-minute intervals ending a few minutes before the data was
  generated, so the seeded history reads naturally as "recent" on a
  live-style dashboard. The clinical *values* (HR/SpO2/Temp) and their
  relative order are untouched.
- Sparse fields (mainly `Temp`, which real ICU monitors only sample
  intermittently) were forward/backward-filled per patient, the same
  "hold last value" approach a bedside monitor display uses between
  readings.

## Regenerating / extending

`seed_clinical_data.py` loads this CSV into the app database once, on
first boot (see `backend/app.py`). To pull a larger sample directly
from PhysioNet yourself, see the Challenge page above -- the full
training set (`training_setA` + `training_setB`) is ~42 MB across
~40,000 per-patient `.psv` files with the same column layout.
