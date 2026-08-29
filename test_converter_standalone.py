import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _install_fake_zeep():
    """n_migrate.integrations.converter_standalone imports zeep at module
    load time; since zeep isn't installed in this test environment
    (and is an optional extra even where it is), we inject a fake
    module into sys.modules before importing our module, then reload.
    """
    fake_zeep = types.ModuleType("zeep")
    fake_zeep.Client = MagicMock()
    fake_transports = types.ModuleType("zeep.transports")
    fake_transports.Transport = MagicMock()
    sys.modules["zeep"] = fake_zeep
    sys.modules["zeep.transports"] = fake_transports

    fake_requests = types.ModuleType("requests")
    fake_requests.Session = MagicMock()
    sys.modules.setdefault("requests", fake_requests)

    import importlib
    import n_migrate.integrations.converter_standalone as mod
    importlib.reload(mod)
    return mod


@pytest.fixture()
def mod():
    m = _install_fake_zeep()
    yield m
    sys.modules.pop("zeep", None)
    sys.modules.pop("zeep.transports", None)


def test_client_requires_zeep_when_unavailable():
    # Simulate zeep genuinely missing (no fake installed).
    sys.modules.pop("zeep", None)
    sys.modules.pop("zeep.transports", None)
    import importlib
    import n_migrate.integrations.converter_standalone as mod
    with patch.dict(sys.modules, {"zeep": None}):
        importlib.reload(mod)
        with pytest.raises(mod.ConverterStandaloneError, match="zeep"):
            mod.ConverterStandaloneClient()
    importlib.reload(mod)  # restore normal state for other tests


def test_connect_logs_in(mod):
    fake_service = MagicMock()
    fake_content = MagicMock()
    fake_content.sessionManager = MagicMock()
    fake_content.conversionManager = MagicMock()
    fake_content.queryManager = MagicMock()
    fake_service.RetrieveContent.return_value = fake_content

    fake_client_instance = MagicMock()
    fake_client_instance.service = fake_service
    mod.zeep.Client = MagicMock(return_value=fake_client_instance)

    client = mod.ConverterStandaloneClient()
    client.connect("converter.lab.local", username="admin", password="pw")

    fake_service.Login.assert_called_once()
    call_args = fake_service.Login.call_args[0]
    assert call_args[1] == "admin"
    assert call_args[2] == "pw"


def test_get_job_status_maps_fields(mod):
    fake_service = MagicMock()
    fake_content = MagicMock()
    fake_content.sessionManager = MagicMock()
    fake_content.conversionManager = MagicMock()
    fake_content.queryManager = MagicMock()
    fake_service.RetrieveContent.return_value = fake_content

    fake_client_instance = MagicMock()
    fake_client_instance.service = fake_service
    mod.zeep.Client = MagicMock(return_value=fake_client_instance)

    fake_info = MagicMock()
    fake_info.state = "completed"
    fake_info.percentComplete = 100
    fake_info.error = None
    fake_service.GetJobInfo.return_value = fake_info

    client = mod.ConverterStandaloneClient()
    client.connect("converter.lab.local", username="admin", password="pw")
    status = client.get_job_status("job-123")

    assert status["state"] == "completed"
    assert status["percent_complete"] == 100


def test_wait_for_job_returns_on_terminal_state(mod):
    fake_service = MagicMock()
    fake_content = MagicMock()
    fake_content.sessionManager = MagicMock()
    fake_content.conversionManager = MagicMock()
    fake_content.queryManager = MagicMock()
    fake_service.RetrieveContent.return_value = fake_content

    fake_client_instance = MagicMock()
    fake_client_instance.service = fake_service
    mod.zeep.Client = MagicMock(return_value=fake_client_instance)

    fake_info = MagicMock(state="completed", percentComplete=100, error=None)
    fake_service.GetJobInfo.return_value = fake_info

    client = mod.ConverterStandaloneClient()
    client.connect("converter.lab.local", username="admin", password="pw")
    status = client.wait_for_job("job-123", poll_interval=0)

    assert status["state"] == "completed"
