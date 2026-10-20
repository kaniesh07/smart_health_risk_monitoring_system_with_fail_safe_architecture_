"""
Smoke tests for the deployed API surface. Run from the project root:

    pip install -r requirements-dev.txt
    pytest -q
"""
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fresh_app(tmp_path, monkeypatch, api_key=None):
    monkeypatch.setenv('HEALTH_DB_PATH', str(tmp_path / 'health.db'))
    if api_key:
        monkeypatch.setenv('API_KEY', api_key)
    else:
        monkeypatch.delenv('API_KEY', raising=False)
    # Re-import so config picks up the env and the module-level app is rebuilt.
    for name in [m for m in sys.modules if m == 'backend' or m.startswith('backend.')]:
        del sys.modules[name]
    app_module = importlib.import_module('backend.app')
    return app_module.app.test_client()


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _fresh_app(tmp_path, monkeypatch)


def test_health_endpoints(client):
    assert client.get('/').status_code == 200
    r = client.get('/healthz')
    assert r.status_code == 200 and r.get_json()['status'] == 'ok'


def test_demo_dataset_seeded(client):
    patients = client.get('/api/patients').get_json()
    assert len(patients) == 5
    assert all(p['is_demo'] == 1 for p in patients)
    vitals = client.get(f"/api/vitals/{patients[0]['id']}?limit=5").get_json()
    assert len(vitals) == 5


def test_live_reading_switches_live_status(client):
    assert client.get('/api/live_status').get_json()['live'] is False
    r = client.post('/api/vitals', json={
        'patient_id': 1, 'hr': 135, 'spo2': 86, 'temperature': 39.4,
        'movement': 0.02, 'device_id': 'TEST-01',
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body['anomaly'] is True and body['alert_level'] >= 2
    status = client.get('/api/live_status').get_json()
    assert status['live'] is True and status['device_id'] == 'TEST-01'


@pytest.mark.parametrize('payload,code', [
    ({'patient_id': 1, 'hr': 'abc', 'spo2': 97, 'temperature': 37}, 400),
    ({'patient_id': 1, 'hr': 70}, 400),
    ({'patient_id': 9999, 'hr': 70, 'spo2': 97, 'temperature': 37}, 404),
])
def test_bad_vitals_rejected(client, payload, code):
    r = client.post('/api/vitals', json=payload)
    assert r.status_code == code
    assert 'error' in r.get_json()


def test_non_json_body_is_400_not_500(client):
    r = client.post('/api/vitals', data='not json', content_type='text/plain')
    assert r.status_code == 400


def test_create_patient(client):
    r = client.post('/api/patient', json={'name': 'Ravi', 'age': 70, 'health_id': ''})
    assert r.status_code == 201
    r2 = client.post('/api/patient', json={'name': 'Asha', 'age': 60, 'health_id': ''})
    assert r2.status_code == 201  # empty health_id must not collide


def test_unknown_route_is_json(client):
    r = client.get('/api/nope')
    assert r.status_code == 404 and r.is_json


def test_api_key_enforced(tmp_path, monkeypatch):
    c = _fresh_app(tmp_path, monkeypatch, api_key='s3cret')
    assert c.get('/api/patients').status_code == 401
    assert c.get('/api/patients', headers={'X-API-Key': 'wrong'}).status_code == 401
    assert c.get('/api/patients', headers={'X-API-Key': 's3cret'}).status_code == 200
    assert c.get('/healthz').status_code == 200  # probes stay open
