"""
ml/train_model.py
------------------
Trains a Logistic Regression anomaly classifier.

Training data is still synthetic-but-clinically-informed (four labelled
scenarios: tachycardia, hypoxia, fever, bradycardia) -- this is a
deliberate modelling choice, not the bug that was fixed elsewhere in this
project. The *dashboard's* data source (previously a random-number
`simulate.py` generator) is what changed: it's now the real PhysioNet
clinical dataset in data/clinical_dataset.csv. This script additionally
sanity-checks the trained model against that real dataset in step 5, since
its SepsisLabel column gives a real (if sparse/imbalanced) ground truth.

Saves model.pkl + scaler.pkl to the same directory.

Run from project root:
    python -m ml.train_model
"""
import os
import csv
import pickle
import numpy as np
from sklearn.linear_model    import LogisticRegression
from sklearn.preprocessing   import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics         import classification_report, accuracy_score

from ml.synthetic_data import generate_dataset, SEED

N = 2000  # samples per class

# -- 1. Synthetic data generation --------------------------------------------------
# Scenario definitions live in ml/synthetic_data.py -- shared with
# evaluate.py so training and evaluation can never silently drift apart.
X, y, _is_critical = generate_dataset(n_per_class=N, seed=SEED)


# -- 2. Train / test split -----------------------------------------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=SEED, stratify=y
)

scaler = StandardScaler()
X_train_sc = scaler.fit_transform(X_train)
X_test_sc = scaler.transform(X_test)


# -- 3. Train --------------------------------------------------------------------------

clf = LogisticRegression(max_iter=1000, random_state=SEED, C=1.0)
clf.fit(X_train_sc, y_train)

y_pred = clf.predict(X_test_sc)
print("\n-- Classification Report (synthetic held-out set) --------------------")
print(classification_report(y_test, y_pred, target_names=['Normal', 'Anomaly']))
print(f"Accuracy: {accuracy_score(y_test, y_pred):.4f}\n")


# -- 4. Save artefacts -----------------------------------------------------------------

out_dir = os.path.dirname(__file__)

with open(os.path.join(out_dir, 'model.pkl'), 'wb') as f:
    pickle.dump(clf, f)

with open(os.path.join(out_dir, 'scaler.pkl'), 'wb') as f:
    pickle.dump(scaler, f)

print("Saved -> ml/model.pkl  ml/scaler.pkl")


# -- 5. Optional sanity check against the REAL clinical dataset ------------------------
# Movement isn't present in the real ICU data (see data/README.md), so this is a
# rough check, not a formal evaluation -- SepsisLabel != "anomaly" 1:1. It's just
# a useful smoke test that the model doesn't flag every real reading as abnormal.

real_csv = os.path.join(out_dir, '..', 'data', 'clinical_dataset.csv')
if os.path.exists(real_csv):
    with open(real_csv, newline='') as f:
        rows = list(csv.DictReader(f))
    X_real = np.array([
        [float(r['hr']), float(r['spo2']), float(r['temperature_c']), float(r['movement'])]
        for r in rows
    ])
    X_real_sc = scaler.transform(X_real)
    flagged = clf.predict(X_real_sc)
    print("-- Sanity check on real clinical dataset ------------------------------")
    print(f"{len(rows)} real ICU readings -> model flagged "
          f"{int(flagged.sum())} ({flagged.mean() * 100:.1f}%) as anomalous.")
