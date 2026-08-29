import xml.etree.ElementTree as ET

import pytest

from n_migrate.core.models import DiskSpec, DiskFormat, NICSpec, VMSpec
from n_migrate.core.ovf import OVF_NS, RASD_NS, generate_ovf


def _spec_two_disks_two_nics() -> VMSpec:
    return VMSpec(
        name="test-vm",
        vcpu_count=4,
        memory_mb=8192,
        disks=[
            DiskSpec(path="disk0", format=DiskFormat.VMDK, size_bytes=10 * 1024**3, is_boot_disk=True),
            DiskSpec(path="disk1", format=DiskFormat.VMDK, size_bytes=20 * 1024**3),
        ],
        nics=[
            NICSpec(mac_address="00:11:22:33:44:55", source_network="vswitch0", target_network="VM Network"),
            NICSpec(mac_address="00:11:22:33:44:56", source_network="vswitch1", target_network="DMZ"),
        ],
    )


def test_generate_ovf_requires_disks(tmp_path):
    with pytest.raises(ValueError, match="at least one disk"):
        generate_ovf(_spec_two_disks_two_nics(), [])


def test_generate_ovf_rejects_disks_in_different_dirs(tmp_path):
    d1 = tmp_path / "a"
    d2 = tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    f1 = d1 / "disk0.vmdk"
    f2 = d2 / "disk1.vmdk"
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")
    with pytest.raises(ValueError, match="same directory"):
        generate_ovf(_spec_two_disks_two_nics(), [f1, f2])


def test_generate_ovf_produces_valid_xml_with_expected_structure(tmp_path):
    spec = _spec_two_disks_two_nics()
    disk_paths = []
    for i in range(2):
        p = tmp_path / f"disk{i}.vmdk"
        p.write_bytes(b"fake-vmdk-bytes" * 100)
        disk_paths.append(p)

    ovf_path = generate_ovf(spec, disk_paths)
    assert ovf_path.name == "test-vm.ovf"
    assert ovf_path.exists()

    tree = ET.parse(ovf_path)
    root = tree.getroot()
    assert root.tag == f"{{{OVF_NS}}}Envelope"

    # Two <File> references, one per disk.
    files = root.findall(f".//{{{OVF_NS}}}References/{{{OVF_NS}}}File")
    assert len(files) == 2
    assert {f.get(f"{{{OVF_NS}}}href") for f in files} == {"disk0.vmdk", "disk1.vmdk"}

    # Two <Disk> entries with capacities matching VMSpec (not file size).
    disks = root.findall(f".//{{{OVF_NS}}}DiskSection/{{{OVF_NS}}}Disk")
    assert len(disks) == 2
    capacities = {d.get(f"{{{OVF_NS}}}capacity") for d in disks}
    assert capacities == {str(10 * 1024**3), str(20 * 1024**3)}

    # Two networks declared, matching target_network names.
    networks = root.findall(f".//{{{OVF_NS}}}NetworkSection/{{{OVF_NS}}}Network")
    assert {n.get(f"{{{OVF_NS}}}name") for n in networks} == {"VM Network", "DMZ"}

    # VirtualHardwareSection: CPU + memory + SCSI controller + 2 disks + 2 NICs = 7 items
    items = root.findall(f".//{{{OVF_NS}}}VirtualHardwareSection/{{{OVF_NS}}}Item")
    assert len(items) == 7

    cpu_item = next(
        i for i in items if i.find(f"{{{RASD_NS}}}ResourceType").text == "3"
    )
    assert cpu_item.find(f"{{{RASD_NS}}}VirtualQuantity").text == "4"

    mem_item = next(
        i for i in items if i.find(f"{{{RASD_NS}}}ResourceType").text == "4"
    )
    assert mem_item.find(f"{{{RASD_NS}}}VirtualQuantity").text == "8192"


def test_generate_ovf_falls_back_to_default_network_when_no_nics(tmp_path):
    spec = VMSpec(name="no-nic-vm", vcpu_count=1, memory_mb=1024,
                   disks=[DiskSpec(path="d", format=DiskFormat.VMDK, size_bytes=1024)])
    disk_path = tmp_path / "d.vmdk"
    disk_path.write_bytes(b"x")

    ovf_path = generate_ovf(spec, [disk_path])
    root = ET.parse(ovf_path).getroot()
    networks = root.findall(f".//{{{OVF_NS}}}NetworkSection/{{{OVF_NS}}}Network")
    assert [n.get(f"{{{OVF_NS}}}name") for n in networks] == ["VM Network"]
