"""
ml/synthetic_data.py
----------------------
Single source of truth for the clinically-informed synthetic scenarios
used to train the anomaly classifier (train_model.py) and to evaluate
the full detection pipeline (evaluate.py). Keeping this in one place
guarantees training and evaluation never silently drift apart.

Four anomaly scenarios, each tagged with a clinical severity tier:

  Scenario      | anomaly | critical | Rationale
  --------------|---------|----------|---------------------------------
  tachycardia   |   1     |    0     | Elevated HR alone -- moderate concern
  hypoxia       |   1     |    1     | SpO2 ~85% is a hard red-flag (NEWS2)
  fever         |   1     |    1     | Temp ~39.8C + immobility = sepsis-risk
  bradycardia   |   1     |    1     | HR ~42 + near-immobile = red-flag

The critical/non-critical split is a modelling decision documented here
explicitly (loosely NEWS2-inspired: SpO2 < 91, Temp > 39.0, HR < 45 are
each independently red-flag thresholds) -- it is NOT a real clinical
scoring system and should be revisited before any clinical use.
"""
import numpy as np

SEED = 42


def make_normal(n, rng):
    return np.column_stack([
        rng.normal(75,   8,    n),   # HR       bpm
        rng.normal(97,   1.2,  n),   # SpO2     %
        rng.normal(37.0, 0.25, n),   # Temp     degC
        rng.uniform(0.3, 1.0,  n),   # Movement
    ])


def make_anomaly(n, rng):
    """Returns (X, is_critical) for n anomalous samples, 4 scenarios, equal split."""
    q = n // 4

    tachycardia = np.column_stack([
        rng.normal(135, 10, q), rng.normal(95, 2, q),
        rng.normal(37.2, 0.3, q), rng.uniform(0.1, 0.4, q),
    ])
    hypoxia = np.column_stack([
        rng.normal(110, 12, q), rng.normal(85, 4, q),
        rng.normal(37.0, 0.2, q), rng.uniform(0.0, 0.1, q),
    ])
    fever = np.column_stack([
        rng.normal(105, 8, q), rng.normal(94, 2, q),
        rng.normal(39.8, 0.5, q), rng.uniform(0.0, 0.2, q),
    ])
    rem = n - 3 * q
    bradycardia = np.column_stack([
        rng.normal(42, 5, rem), rng.normal(96, 1, rem),
        rng.normal(36.5, 0.3, rem), rng.uniform(0.0, 0.05, rem),
    ])

    X = np.vstack([tachycardia, hypoxia, fever, bradycardia])
    is_critical = np.array([0] * q + [1] * q + [1] * q + [1] * rem)
    return X, is_critical


def generate_dataset(n_per_class=2000, seed=SEED):
    """
    Returns X, y, is_critical (all length 2*n_per_class):
      y            -> 0 normal / 1 anomaly
      is_critical  -> 1 only for rows that are BOTH anomalous AND
                       clinically red-flag severity (0 for normal rows too)
    """
    rng = np.random.default_rng(seed)
    X_normal = make_normal(n_per_class, rng)
    X_anom, crit = make_anomaly(n_per_class, rng)

    X = np.vstack([X_normal, X_anom])
    y = np.array([0] * n_per_class + [1] * n_per_class)
    is_critical = np.concatenate([np.zeros(n_per_class, dtype=int), crit])
    return X, y, is_critical
