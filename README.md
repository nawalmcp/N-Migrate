# N-Migrate

**Open-source VM migration platform** — a free alternative to VMware
vCenter Converter, for moving VMs between VMware, Hyper-V, and
KVM/Proxmox (with P2V and cloud targets on the roadmap).

> **Status: early, feature-complete scaffold.** Core architecture, all
> three hypervisor adapter pairs, multi-disk VMware import (OVF-based),
> the CLI, the REST API + async job queue, and CI are all implemented.
> **Nothing has been run against real infrastructure yet** — see
> [`LAB_TESTING.md`](LAB_TESTING.md) for the validation procedure, and
> [Roadmap](#roadmap) for what's still missing outright (warm
> migration, P2V, cloud targets).

## How it works

```
source hypervisor --[extract]--> VMSpec + raw disk(s)
                                        |
                                  [convert: qemu-img + virt-v2v]
                                        |
                                        v
                          converted disk(s) + updated VMSpec
                                        |
                                  [deploy: target adapter]
                                        v
                              target hypervisor (VM defined + powered on)
```

Rather than reimplementing disk format conversion and guest OS
adaptation (VirtIO driver injection, bootloader fixups, VMware
Tools/Hyper-V integration services removal), N-Migrate wraps two
mature, LGPL-licensed tools:

- **`qemu-img`** — disk *format* conversion (vmdk ⇄ vhdx ⇄ qcow2 ⇄ raw)
- **`virt-v2v`** (libguestfs) — guest OS conversion

Two ways to drive it:
- **CLI** (`n-migrate migrate ...`) — synchronous, one VM at a time, simplest to debug.
- **REST API + Celery** (`n_migrate/api/`) — async job queue, DB-backed status polling, for building a UI or automating batches of VMs on top of.

## Requirements

| Tool | Why | Install |
|---|---|---|
| Python 3.10+ | runtime | — |
| `qemu-img` | disk format conversion | `apt install qemu-utils` |
| `virt-v2v` | guest OS conversion | `apt install libguestfs-tools virt-v2v` |
| `libvirt` + dev headers | KVM/Proxmox adapters | `apt install libvirt-dev` |
| `ovftool` (optional) | VMware export/import | download from Broadcom (proprietary, not bundled) |
| WinRM enabled on Hyper-V host | Hyper-V adapters | `Enable-PSRemoting -Force` on the Windows host |
| Redis (API path only) | Celery broker/backend | `docker compose up redis`, or any Redis instance |

**Hyper-V note:** the Hyper-V adapters move disk files over the
Windows admin share (`\\host\C$\...`) using the same credentials as
WinRM. If admin shares are disabled in your environment, pass a
custom `export_share`/`target_share` (see `adapters/*/hyperv.py`).

**VMware multi-disk note:** since `ovftool` can only import a
standalone `.vmdk` when a VM has exactly one disk, VMs with 2+ disks
are packaged into a minimal generated OVF first (`core/ovf.py`) so
all disks + NICs import as a unit.

```bash
git clone <your-repo-url> n-migrate
cd n-migrate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # CLI only
pip install -e ".[api,dev]"    # + REST API / Celery
```

## Usage — CLI

```bash
# List VMs on a source
n-migrate list-vms --source kvm --source-uri qemu:///system

# Migrate KVM -> VMware
n-migrate migrate \
  --vm my-old-vm \
  --source kvm --source-uri qemu:///system \
  --target vmware \
  --target-host vc.example.com \
  --target-user 'administrator@vsphere.local' \
  --target-password '***' \
  --target-datastore datastore1 \
  --network-map vswitch0:VM-Network

# Migrate VMware -> KVM
n-migrate migrate \
  --vm old-windows-vm \
  --source vmware --source-host vc.example.com \
  --source-user 'administrator@vsphere.local' --source-password '***' \
  --target kvm --target-uri "qemu+ssh://root@kvm-host/system" \
  --network-map "VM Network:br0"
```

## Usage — Physical-to-Virtual (Experimental)

Real P2V (a live physical or otherwise-inaccessible-to-our-adapters
machine as the source) delegates to a VMware/Broadcom **Converter
Standalone server** you already run -- see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for why this is an
optional integration rather than something built into the core
pipeline, and the module docstring in
`n_migrate/integrations/converter_standalone.py` for its verified-vs-
best-effort status (**unverified against a real server** -- start here
if debugging).

```bash
pip install -e ".[converter]"   # installs zeep

n-migrate p2v \
  --vm-name migrated-physical-box \
  --converter-host converter.lab.local --converter-user admin --converter-password '***' \
  --source-hostname 192.168.1.50 --source-username Administrator --source-password '***' \
  --target-vc-host vc.lab.local --target-vc-user 'administrator@vsphere.local' --target-vc-password '***' \
  --target-compute-resource Cluster01
```

## Usage — REST API

```bash
docker compose up --build   # Redis + API (:8000) + Celery worker
```

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "vm_name": "my-old-vm",
    "source_platform": "kvm",
    "source_credentials": {"uri": "qemu:///system"},
    "target_platform": "kvm",
    "target_credentials": {"uri": "qemu+ssh://root@kvm-host-2/system"},
    "network_mapping": {"default": "default"}
  }'
# -> 202, {"id": "...", "status": "queued", ...}

curl http://localhost:8000/api/jobs/<id>   # poll for status
```

Interactive docs at `http://localhost:8000/docs`. See
[`LAB_TESTING.md`](LAB_TESTING.md) for the full walkthrough, including
running the worker outside Docker when your hypervisors are on a
network the container can't reach.

## Project layout

```
n_migrate/
├── core/
│   ├── models.py            # VMSpec, DiskSpec, NICSpec, MigrationJob -- the shared contract
│   ├── conversion.py         # qemu-img / virt-v2v wrappers
│   ├── orchestration.py      # extract -> convert -> deploy state machine
│   ├── ovf.py                 # minimal OVF generator (multi-disk VMware import)
│   └── adapter_factory.py     # shared adapter construction (CLI + API)
├── adapters/
│   ├── base.py                 # SourceAdapter / TargetAdapter interfaces
│   ├── source/{kvm,vmware,hyperv}.py
│   └── target/{kvm,vmware,hyperv}.py
├── cli/main.py                 # `n-migrate` command (Typer)
├── api/
│   ├── main.py                  # FastAPI app
│   ├── tasks.py                  # Celery task (async migration execution)
│   ├── db.py                      # SQLModel job persistence (SQLite by default)
│   └── schemas.py                 # request/response models
tests/                           # pytest, adapters + Celery mocked -- no real hypervisor needed
Dockerfile / docker-compose.yml  # API + worker + Redis, one command
LAB_TESTING.md                   # real-infrastructure validation procedure
```

**Adding a new hypervisor** = implement `SourceAdapter` and/or
`TargetAdapter` from `adapters/base.py`. Nothing else needs to change —
conversion, orchestration, the CLI, and the API are all hypervisor-agnostic.

## Roadmap

- [x] Core VMSpec/Job models
- [x] KVM/libvirt source + target adapter
- [x] VMware source + target adapter (via ovftool; VDDK swap-in documented)
- [x] Hyper-V source + target adapter (WinRM + SMB2, admin-share based)
- [x] Conversion engine (qemu-img + virt-v2v wrappers, target-aware final format)
- [x] Multi-disk VMware target import (generated OVF + streamOptimized VMDKs)
- [x] CLI: `list-vms`, `migrate` (all three platforms wired in)
- [x] REST API + Celery async job queue + SQLite/Postgres persistence
- [x] Docker Compose lab stack (Redis + API + worker)
- [x] CI (GitHub Actions: lint, type-check, test, build-check on 3.10/3.11/3.12)
- [ ] **Integration testing against real libvirt/vSphere/Hyper-V labs** — see `LAB_TESTING.md`; this is the current priority
- [x] Physical-to-Virtual (P2V), experimental — via an optional integration with a user-run VMware/Broadcom Converter Standalone server (`n-migrate p2v`); see `THIRD_PARTY_NOTICES.md` and the module docstring for what's verified vs. best-effort
- [ ] Web dashboard
- [ ] Warm/live migration via CBT (VMware) / incremental block backup (libvirt)
- [ ] Cloud targets (AWS/Azure/GCP)
- [ ] Secrets-manager integration for API credentials (currently transit the Celery broker as plaintext task args -- fine for a trusted lab network, not for production as-is)

## Contributing

Issues and PRs welcome. The biggest gap right now is real-world
validation: every adapter is written against each platform's
documented API/cmdlet behavior and covered with mocked unit tests, but
none of it has run against an actual vCenter, Hyper-V host, or libvirt
cluster yet. **Run through [`LAB_TESTING.md`](LAB_TESTING.md) against
your own lab and file issues for what breaks** — that's the most
valuable contribution possible right now.

## License

Apache 2.0 — see `LICENSE`.
