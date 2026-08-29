# N-Migrate — Lab Testing Guide

This is a from-scratch procedure for validating N-Migrate against real
infrastructure. Nothing in this codebase has been run against a real
hypervisor yet (see main README's Roadmap) — this guide is written so
you can be the first to find out what breaks.

**Do this on disposable test VMs, on an isolated/lab network, not
production.** Cold migration means the source VM gets shut down (or
you shut it down yourself before exporting) — treat every run as
destructive until you've verified round-trip correctness.

---

## 1. What you're testing

Two independent paths exercise the same underlying code:

- **CLI path** (`n-migrate migrate ...`) — simplest to debug, run this first.
- **API path** (FastAPI + Celery) — exercises the async job queue and DB persistence; test this second, once the CLI path works for a given platform pair.

Test **one platform pair at a time**, starting with **KVM → KVM**
(fewest moving parts — no `ovftool`, no WinRM, just libvirt on both
ends) before adding VMware or Hyper-V.

---

## 2. Controller machine requirements

The controller is whatever machine runs `n-migrate` (CLI) or the
API+worker. It needs network access to *both* the source and target
hypervisors.

| Requirement | Why | Check |
|---|---|---|
| Linux (Ubuntu 22.04/24.04 tested-against, not tested-on) | `virt-v2v`/`libguestfs` are Linux-only | — |
| Python 3.10+ | runtime | `python3 --version` |
| `qemu-img` | disk format conversion | `apt install qemu-utils` |
| `virt-v2v` + `libguestfs-tools` | guest OS conversion | `apt install libguestfs-tools virt-v2v` |
| `libvirt-dev` | builds `libvirt-python` | `apt install libvirt-dev pkg-config gcc` |
| `ovftool` (VMware paths only) | VMware export/import | download from Broadcom Support Portal (free account required, proprietary — not bundled) |
| ~2x source VM disk size free space | extraction + conversion both land on local disk before upload | `df -h` on wherever `/tmp` or your configured work dir lives |
| Network route to source AND target hypervisor management interfaces | obviously | `ping`/`telnet <host> 443` (vSphere), `5985`/`5986` (WinRM), `22` or libvirt's port (KVM) |

Install everything:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libvirt-dev pkg-config gcc \
    qemu-utils libguestfs-tools

git clone <your-repo-url> n-migrate && cd n-migrate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"
```

Verify the two external binaries are actually on PATH before going further:

```bash
qemu-img --version
virt-v2v --version
```

If `virt-v2v --version` fails with a libguestfs/supermin error, that's
almost always a kernel/appliance mismatch — see
[Troubleshooting](#troubleshooting) below before doing anything else;
nothing downstream will work until this passes.

---

## 3. Source/target lab environment requirements

### 3.1 KVM / Proxmox

- A libvirt-manageable host (local `qemu:///system`, or remote via `qemu+ssh://user@host/system`).
- At least one test VM, powered off (cold migration), with a virtio or IDE disk.
- If remote: SSH key-based auth from the controller to the KVM host (libvirt's `qemu+ssh://` shells out to `ssh`).
- Controller needs read access to the VM's backing disk file path as it appears in the domain XML (local filesystem path for `qemu:///system`; for remote hosts see the `TODO` in `adapters/source/kvm.py::export_disks` — as shipped, remote KVM source export assumes the disk path is reachable, which usually means running the controller *on* the KVM host, or you need to implement the streaming-copy TODO first).

### 3.2 VMware (vCenter or standalone ESXi)

- vCenter or ESXi ≥ 6.7, reachable over HTTPS (443) from the controller.
- An account with, at minimum: VM export privileges (source), and Datastore + Network + VM-create privileges (target).
- Target: a known datastore name and portgroup/network names that exactly match what you'll pass via `--network-map`.
- `ovftool` installed on the controller and confirmed working against your vCenter (`ovftool --noSSLVerify vi://user:pass@host` should list something without erroring).
- A test VM with VMware Tools installed (helps virt-v2v identify the guest cleanly) — powered off before export.

### 3.3 Hyper-V

- Windows Server 2019+ or Windows 10/11 Pro+ with Hyper-V role enabled.
- `Enable-PSRemoting -Force` run on the Hyper-V host (WinRM listener on 5985).
- The account used has local admin rights on the Hyper-V host (needed for `Export-VM`/`New-VM` and for admin-share access).
- **Admin share (`C$`) reachable from the controller** — this is the adapters' file-transfer mechanism (see `adapters/*/hyperv.py` docstrings). Test with:
  ```bash
  smbclient //hyperv-host/C$ -U 'DOMAIN\user' -c 'ls'
  ```
  If this fails, either enable admin shares (`Set-SmbServerConfiguration -EnableSharedFolders`... actually admin shares are on by default unless `LocalAccountTokenFilterPolicy` blocks remote admin access for local accounts — set that registry key to `1` if using a local (non-domain) admin account) or point the adapters at a custom share via the `export_share`/`target_share` kwargs.
- A test VM, powered off, Generation 1 or 2.
- Firewall: allow WinRM (TCP 5985) and SMB (TCP 445) from the controller's IP.

---

## 4. CLI test procedure

### 4.1 Smoke test — list VMs (no conversion, validates connectivity + auth only)

```bash
# KVM
n-migrate list-vms --source kvm --source-uri qemu:///system

# VMware
n-migrate list-vms --source vmware \
  --source-host vc.lab.local --source-user 'administrator@vsphere.local' \
  --source-password 'REDACTED'

# Hyper-V
n-migrate list-vms --source hyperv \
  --source-host hyperv-host.lab.local --source-user 'Administrator' \
  --source-password 'REDACTED'
```

Confirm your test VM's name appears in the output before proceeding.
If this step fails, nothing else will work — fix connectivity/auth
first (see Troubleshooting).

### 4.2 First real migration — KVM → KVM (lowest-risk starting point)

```bash
n-migrate --verbose migrate \
  --vm test-vm-01 \
  --source kvm --source-uri qemu:///system \
  --target kvm --target-uri "qemu+ssh://root@kvm-host-2.lab.local/system" \
  --network-map "default:default"
```

`--verbose` gets you DEBUG-level logging including the exact
`qemu-img`/`virt-v2v` commands run — keep it on for every lab test run.

**What to check after it completes:**
1. `virsh list --all` on the target host shows the new domain.
2. `virsh start <vm-name>` boots it (if `power_on()` didn't already do this).
3. Console/VNC into it — does the guest OS boot cleanly? Network adapter present with the right IP config (DHCP will just work; static IPs need the mapped network to actually route the same way).
4. Compare guest-visible disk contents against the source (spot-check a few files) to confirm the conversion didn't corrupt anything.

### 4.3 KVM → VMware

```bash
n-migrate --verbose migrate \
  --vm test-vm-01 \
  --source kvm --source-uri qemu:///system \
  --target vmware \
  --target-host vc.lab.local \
  --target-user 'administrator@vsphere.local' --target-password 'REDACTED' \
  --target-datastore datastore1 \
  --target-network 'VM Network' \
  --network-map "default:VM Network"
```

Check in vCenter: VM appears with correct CPU/memory, disk(s) attached
and the right size, NIC on the mapped portgroup, boots without a
"missing OS" or purple-screen error (which would indicate the
virt-v2v/bootloader step needs attention for that guest OS).

### 4.4 VMware → Hyper-V, Hyper-V → KVM, etc.

Same pattern — swap `--source`/`--target` and their respective flags.
Test every direction you actually plan to support in production;
don't assume symmetry (P2V-style detail differs per direction, e.g.
UEFI/BIOS firmware translation is the most common breakage point).

### 4.5 Multi-disk VM

Specifically test a VM with 2+ disks once single-disk works — this
exercises the OVF-generation path (`core/ovf.py`) for VMware targets,
which is new and unverified against a real `ovftool`/vCenter import.
Check that **disk order** on the target matches the source (boot disk
first) and that a second data disk's filesystem mounts cleanly.

---

## 5. API test procedure

### 5.1 Bring up the stack

```bash
docker compose up --build
```

This starts Redis, the FastAPI app (port 8000), and a Celery worker.
**Caveat:** the worker container only has network access to whatever
Docker's network provides — if your hypervisors are on an isolated
lab VLAN the container can't reach, run the worker directly on the
controller host instead:

```bash
# instead of `docker compose up worker`
redis-server &  # or use the compose redis service, exposed on 6379
export N_MIGRATE_BROKER_URL=redis://localhost:6379/0
celery -A n_migrate.api.tasks worker --loglevel=info
```

### 5.2 Health check

```bash
curl http://localhost:8000/api/health
# {"status": "ok"}
```

### 5.3 List VMs

```bash
curl -X POST http://localhost:8000/api/vms/list \
  -H 'Content-Type: application/json' \
  -d '{
    "platform": "kvm",
    "credentials": {"uri": "qemu:///system"}
  }'
```

### 5.4 Start a migration job

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "vm_name": "test-vm-01",
    "source_platform": "kvm",
    "source_credentials": {"uri": "qemu:///system"},
    "target_platform": "kvm",
    "target_credentials": {"uri": "qemu+ssh://root@kvm-host-2.lab.local/system"},
    "network_mapping": {"default": "default"}
  }'
```

Response is `202` with a job `id`. Poll it:

```bash
watch -n 2 curl -s http://localhost:8000/api/jobs/<job-id>
```

Expect `status` to move through
`queued → extracting → converting → transferring → deploying → verifying → done`
(or `failed`, with `error_message` populated — check the worker's
console output for the full traceback, the API only surfaces the
final exception message).

### 5.5 Interactive API docs

FastAPI auto-generates a test UI at `http://localhost:8000/docs` —
useful for exploring the schema without hand-writing curl commands.

---

## 6. Suggested test matrix

Run these roughly in order — each unlocks confidence in the next:

| # | Source | Target | Disks | Purpose |
|---|---|---|---|---|
| 1 | KVM | KVM | 1 | Baseline: conversion pipeline works at all |
| 2 | KVM | KVM | 2+ | Multi-disk on the simplest target |
| 3 | KVM | VMware | 1 | ovftool single-disk import path |
| 4 | KVM | VMware | 2+ | **New/unverified**: OVF-based multi-disk import |
| 5 | VMware | KVM | 1 | Export via ovftool, virt-v2v handles VMware Tools removal |
| 6 | KVM | Hyper-V | 1 | SMB upload + New-VM path |
| 7 | Hyper-V | KVM | 1 | Export-VM + SMB download path |
| 8 | any | any | 1, Windows guest | VirtIO driver injection actually lets Windows boot |
| 9 | any | any | 1, Linux guest, static IP | Network config survives the NIC re-map |

---

## 7. Troubleshooting

**`virt-v2v --version` fails / supermin appliance errors**
Usually a mismatch between the running kernel and what libguestfs's
appliance expects. Try `sudo update-guestfs-appliance` (if available)
or `LIBGUESTFS_BACKEND=direct virt-v2v --version` to bypass the
supermin appliance. This is a well-documented libguestfs pain point —
search the exact error text, most are covered in libguestfs's own FAQ.

**`ovftool: command not found`**
It's not on PATH after install — check `/usr/lib/vmware-ovftool/` and
add it, or use the installer's default PATH update option.

**ovftool import fails with a certificate error**
Add `--noSSLVerify` (already in both adapters) or install vCenter's
CA cert on the controller for a cleaner fix.

**SMB connection refused / access denied (Hyper-V adapters)**
- Confirm `Enable-PSRemoting -Force` was run.
- Confirm admin shares are enabled (see §3.3).
- If using a local (non-domain) account, set
  `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\LocalAccountTokenFilterPolicy`
  to `1` (DWORD) and restart — otherwise Windows silently downgrades
  local admin accounts connecting remotely to non-admin, which blocks
  admin-share access even though WinRM itself succeeds.

**libvirt "Permission denied" on disk files**
`qemu:///system` runs as a service account (often `libvirt-qemu`) —
if you're extracting/copying disks as your own user, check file
ownership/SELinux contexts. `ausearch -m avc -ts recent` if SELinux
is enforcing and something is silently denied.

**Converted VM boots to a black screen / "no bootable device"**
Usually a firmware mismatch (BIOS vs UEFI) between source and target
metadata detection — check the `firmware` field N-Migrate detected
(`--verbose` logs the `VMSpec`) against what the source VM actually
uses, and file an issue with the source platform + guest OS if it's
wrong; the adapters' firmware-detection heuristics are new and
untested against edge cases (e.g. VMware VMs with `firmware` unset
explicitly in config).

**Job stuck in `queued` forever (API path)**
No worker is running, or it can't reach Redis — check
`celery -A n_migrate.api.tasks worker --loglevel=info` output for a
connection error.

---

## 8. Physical-to-Virtual (Converter Standalone) — separate, higher-risk track

This is a distinct, unverified code path (`n_migrate/integrations/converter_standalone.py`,
`n-migrate p2v`) — treat it as its own testing effort, not part of the
matrix above.

**Prerequisites:**
- A running VMware/Broadcom Converter Standalone server (download from
  Broadcom directly — see `THIRD_PARTY_NOTICES.md`).
- `pip install -e ".[converter]"` on the controller.
- A physical (or live, network-reachable) test machine to convert —
  Windows is the better-trodden path for Converter Standalone itself.
- A target vCenter, since the P2V job spec requires a managed
  destination.

**Before running a real job**, sanity-check connectivity first:

```python
from n_migrate.integrations.converter_standalone import ConverterStandaloneClient

client = ConverterStandaloneClient()
client.connect("converter.lab.local", username="admin", password="***")
print(client.query_source("192.168.1.50", "Administrator", "***"))
```

If `connect()` fails on the WSDL fetch, open
`https://<converter-host>:443/converter/sdk?wsdl` in a browser to find
the actual URL your server exposes and pass it via `wsdl_url=`.

If `query_source` works but `submit_p2v_job` fails, the most likely
culprits, in order:
1. `ManagedVmLocation`/`TargetVmSpec` field names or types not
   matching your server's exact WSDL (zeep's error will name the
   field) — cross-check against your own copy of the Reference Guide.
2. The `computeResource`/`host`/`resourcePool`/`vmFolder`
   ManagedObjectReference objects (resolved via pyVmomi in
   `_resolve_target_morefs`) not serializing the way zeep expects —
   this is flagged in the module as the least-tested part.

File issues with the exact zeep exception — that traceback is usually
enough to pinpoint which field/type needs adjusting.

---

## 9. What's explicitly NOT covered yet

Don't spend lab time on these — they're known gaps, not bugs to report:

- **Warm/live migration** — not implemented (cold/offline only).
- **P2V (physical source)** — experimental only, via the separate Converter Standalone integration in §8, not the main adapter pipeline.
- **Cloud targets** (AWS/Azure/GCP) — not implemented.
- **Credential security in the API path** — passwords currently transit the Celery/Redis broker as plaintext task arguments. Fine for an isolated lab network; do not point this at production credentials over an untrusted network without adding TLS + auth to Redis first (or swapping in a secrets-manager reference).
- **Snapshot/rollback on failure** — if a migration fails mid-way, the target-side VM (if partially created) is not automatically cleaned up. Check the target hypervisor manually after any `failed` job.

Everything else is fair game — please file issues with the exact CLI
command / API request, `--verbose` log output, and source/target
platform versions.
