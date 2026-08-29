from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from n_migrate.core.conversion import ConversionError, convert_disk_format
from n_migrate.core.models import DiskFormat


def test_convert_disk_format_missing_binary_raises():
    with patch("shutil.which", return_value=None):
        with pytest.raises(ConversionError, match="qemu-img"):
            convert_disk_format(
                Path("/tmp/does-not-matter.vmdk"),
                DiskFormat.VMDK,
                DiskFormat.QCOW2,
                Path("/tmp/out"),
            )


def test_convert_disk_format_success(tmp_path):
    src = tmp_path / "disk.vmdk"
    src.write_bytes(b"fake-disk-content")
    dest_dir = tmp_path / "out"

    fake_proc = MagicMock(returncode=0, stderr="")
    with patch("shutil.which", return_value="/usr/bin/qemu-img"), \
         patch("subprocess.run", return_value=fake_proc) as run_mock:
        result = convert_disk_format(src, DiskFormat.VMDK, DiskFormat.QCOW2, dest_dir)

    assert result.output_format == DiskFormat.QCOW2
    assert result.output_path.name == "disk.qcow2"
    called_cmd = run_mock.call_args[0][0]
    assert "qemu-img" in called_cmd[0]
    assert "-f" in called_cmd and "vmdk" in called_cmd
    assert "-O" in called_cmd and "qcow2" in called_cmd


def test_convert_disk_format_failure_raises(tmp_path):
    src = tmp_path / "disk.vmdk"
    src.write_bytes(b"fake")
    fake_proc = MagicMock(returncode=1, stderr="boom")
    with patch("shutil.which", return_value="/usr/bin/qemu-img"), \
         patch("subprocess.run", return_value=fake_proc):
        with pytest.raises(ConversionError, match="boom"):
            convert_disk_format(src, DiskFormat.VMDK, DiskFormat.QCOW2, tmp_path / "out")
