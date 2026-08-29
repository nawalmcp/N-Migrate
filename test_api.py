import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh app + isolated SQLite DB per test, so tests don't share state
    or touch a real n_migrate.db file in the repo root.
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("N_MIGRATE_DATABASE_URL", f"sqlite:///{db_path}")

    import n_migrate.api.db as db_module
    importlib.reload(db_module)
    import n_migrate.api.tasks as tasks_module
    importlib.reload(tasks_module)
    import n_migrate.api.main as main_module
    importlib.reload(main_module)

    with TestClient(main_module.app) as c:
        yield c, main_module


def test_health(client):
    c, _ = client
    resp = c.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_get_job(client):
    c, main_module = client
    with patch.object(main_module.execute_migration_task, "delay") as mock_delay:
        resp = c.post("/api/jobs", json={
            "vm_name": "test-vm",
            "source_platform": "kvm",
            "source_credentials": {"uri": "qemu:///system"},
            "target_platform": "kvm",
            "target_credentials": {"uri": "qemu+ssh://root@other-host/system"},
            "network_mapping": {"vswitch0": "br0"},
        })

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["vm_name"] == "test-vm"
    assert body["progress_pct"] == 0.0
    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs["vm_name"] == "test-vm"
    assert call_kwargs["network_mapping"] == {"vswitch0": "br0"}

    job_id = body["id"]
    resp2 = c.get(f"/api/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job_id
    assert resp2.json()["status"] == "queued"


def test_get_unknown_job_returns_404(client):
    c, _ = client
    resp = c.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404


def test_list_jobs_empty(client):
    c, _ = client
    resp = c.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_vms_unknown_platform_returns_400(client):
    c, _ = client
    resp = c.post("/api/vms/list", json={"platform": "nope", "credentials": {}})
    assert resp.status_code == 400


def test_create_job_missing_required_field_returns_422(client):
    c, _ = client
    resp = c.post("/api/jobs", json={"vm_name": "test-vm"})  # missing platforms/creds
    assert resp.status_code == 422
