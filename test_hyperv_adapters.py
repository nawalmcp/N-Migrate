import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from n_migrate.adapters.source.hyperv import HyperVSourceAdapter
from n_migrate.adapters.target.hyperv import HyperVTargetAdapter


def _ps_result(stdout: str, code: int = 0) -> MagicMock:
    return MagicMock(status_code=code, std_out=stdout.encode(), std_err=b"")


def test_source_list_vms():
    adapter = HyperVSourceAdapter()
    fake_session = MagicMock()
    fake_session.run_ps.return_value = _ps_result(json.dumps(["vm1", "vm2"]))

    with patch("n_migrate.adapters.source.hyperv.winrm.Session", return_value=fake_session), \
         patch("n_migrate.adapters.source.hyperv.smbclient.register_session"):
        adapter.connect(host="hyperv-host", user="admin", password="pw")
        assert adapter.list_vms() == ["vm1", "vm2"]


def test_source_get_vm_spec():
    adapter = HyperVSourceAdapter()
    fake_session = MagicMock()
    spec_json = json.dumps({
        "CPUCount": 4,
        "MemoryMB": 4096,
        "Generation": 2,
        "Disks": [{"Path": "C:\\VMs\\vm1\\disk.vhdx"}],
        "Nics": [{"MacAddress": "00-11-22-33-44-55", "SwitchName": "External"}],
    })
    fake_session.run_ps.return_value = _ps_result(spec_json)

    with patch("n_migrate.adapters.source.hyperv.winrm.Session", return_value=fake_session), \
         patch("n_migrate.adapters.source.hyperv.smbclient.register_session"), \
         patch("n_migrate.adapters.source.hyperv.smbclient.stat",
               return_value=MagicMock(st_size=123456)):
        adapter.connect(host="hyperv-host", user="admin", password="pw")
        spec = adapter.get_vm_spec("vm1")

    assert spec.vcpu_count == 4
    assert spec.memory_mb == 4096
    assert spec.firmware == "uefi"
    assert spec.disks[0].size_bytes == 123456
    assert spec.nics[0].source_network == "External"


def test_source_export_disks_downloads_over_smb(tmp_path):
    adapter = HyperVSourceAdapter()
    fake_session = MagicMock()
    fake_session.run_ps.return_value = _ps_result(
        json.dumps(["C:\\N-Migrate-Exports\\vm1\\Virtual Hard Disks\\disk.vhdx"])
    )

    fake_remote_file = MagicMock()
    fake_remote_file.__enter__.return_value = fake_remote_file
    fake_remote_file.read.side_effect = [b"chunk-data", b""]

    with patch("n_migrate.adapters.source.hyperv.winrm.Session", return_value=fake_session), \
         patch("n_migrate.adapters.source.hyperv.smbclient.register_session"), \
         patch("n_migrate.adapters.source.hyperv.smbclient.open_file",
               return_value=fake_remote_file):
        adapter.connect(host="hyperv-host", user="admin", password="pw")
        paths = adapter.export_disks("vm1", tmp_path)

    assert len(paths) == 1
    assert paths[0].name == "disk.vhdx"
    assert paths[0].read_bytes() == b"chunk-data"


def test_target_register_vm_builds_expected_script():
    from n_migrate.core.models import NICSpec, VMSpec

    adapter = HyperVTargetAdapter()
    fake_session = MagicMock()
    fake_session.run_ps.return_value = _ps_result("")

    spec = VMSpec(
        name="migrated-vm",
        vcpu_count=2,
        memory_mb=2048,
        firmware="uefi",
        nics=[NICSpec(mac_address="00:11:22:33:44:55", source_network="vswitch0",
                       target_network="External")],
    )

    with patch("n_migrate.adapters.target.hyperv.winrm.Session", return_value=fake_session), \
         patch("n_migrate.adapters.target.hyperv.smbclient.register_session"):
        adapter.connect(host="target-host", user="admin", password="pw")
        result_name = adapter.register_vm(spec, ["C:\\N-Migrate-VMs\\migrated-vm\\disk.vhdx"])

    assert result_name == "migrated-vm"
    script_used = fake_session.run_ps.call_args[0][0]
    assert "New-VM -Name 'migrated-vm'" in script_used
    assert "-Generation 2" in script_used
    assert "Add-VMNetworkAdapter -VMName 'migrated-vm' -SwitchName 'External'" in script_used
