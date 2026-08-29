from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from n_migrate.adapters.base import SourceAdapter, TargetAdapter
from n_migrate.core.conversion import ConversionResult
from n_migrate.core.models import DiskFormat, DiskSpec, JobStatus, MigrationJob, VMSpec
from n_migrate.core.orchestration import MigrationError, run_migration


class FakeSource(SourceAdapter):
    platform_name = "fake-src"

    def connect(self, **credentials): pass

    def list_vms(self): return ["vm1"]

    def get_vm_spec(self, vm_identifier):
        return VMSpec(
            name=vm_identifier,
            vcpu_count=2,
            memory_mb=2048,
            disks=[DiskSpec(path="/tmp/disk.vmdk", format=DiskFormat.VMDK, size_bytes=1024)],
        )

    def export_disks(self, vm_identifier, dest_dir):
        return [Path("/tmp/disk.vmdk")]

    def disconnect(self): pass


class FakeTarget(TargetAdapter):
    platform_name = "fake-tgt"

    def connect(self, **credentials): pass

    def upload_disk(self, local_path, vm_name): return str(local_path)

    def register_vm(self, spec, uploaded_disk_refs): return spec.name

    def power_on(self, vm_identifier): pass

    def disconnect(self): pass


def test_run_migration_happy_path(tmp_path):
    job = MigrationJob(vm_name="vm1", source_platform="fake-src", target_platform="fake-tgt")
    fake_result = ConversionResult(
        output_path=tmp_path / "disk.qcow2", output_format=DiskFormat.QCOW2, log=""
    )
    with patch("n_migrate.core.orchestration.convert_guest_os", return_value=fake_result):
        result = run_migration(
            job, FakeSource(), FakeTarget(), vm_identifier="vm1", work_dir=tmp_path
        )

    assert result.status == JobStatus.DONE
    assert result.progress_pct == 100.0
    assert result.error_message is None


def test_run_migration_no_disks_fails(tmp_path):
    class NoDiskSource(FakeSource):
        def export_disks(self, vm_identifier, dest_dir):
            return []

    job = MigrationJob(vm_name="vm1", source_platform="fake-src", target_platform="fake-tgt")
    with pytest.raises(MigrationError):
        run_migration(job, NoDiskSource(), FakeTarget(), vm_identifier="vm1", work_dir=tmp_path)

    assert job.status == JobStatus.FAILED
    assert job.error_message is not None
