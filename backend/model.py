import pickle
import os
import numpy as np

_MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'ml', 'model.pkl')
_SCALER_PATH = os.path.join(os.path.dirname(__file__), '..', 'ml', 'scaler.pkl')

_model = None
_scaler = None


def load_model():
    global _model, _scaler
    if not os.path.exists(_MODEL_PATH):
        # Fresh clone / clean build without the trained artefacts: train
        # now (deterministic, takes ~1s) instead of refusing to boot.
        print("[ML] model.pkl not found -- training it now (python -m ml.train_model).")
        import runpy
        runpy.run_module('ml.train_model', run_name='__main__')
    with open(_MODEL_PATH, 'rb') as f:
        _model = pickle.load(f)
    if os.path.exists(_SCALER_PATH):
        with open(_SCALER_PATH, 'rb') as f:
            _scaler = pickle.load(f)
    print("[ML] Model loaded successfully.")


def predict(hr: float, spo2: float, temperature: float, movement: float):
    """
    Returns (is_anomaly: int, anomaly_probability: float).
    Features: [hr, spo2, temperature, movement]
    """
    global _model, _scaler
    if _model is None:
        load_model()

    X = np.array([[hr, spo2, temperature, movement]])
    if _scaler is not None:
        X = _scaler.transform(X)

    prediction = int(_model.predict(X)[0])
    probability = float(_model.predict_proba(X)[0][1])
    return prediction, probability
