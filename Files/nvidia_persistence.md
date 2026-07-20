# NVIDIA RTX PRO 6000 Blackwell Server Edition Power Limit Notes (Bazzite Linux)

Status: retained operator/lab guidance for the NVIDIA procedures documented
below. LVS does not currently implement or commit to a release any CLI or GUI
control for GPU persistence or power limits. A future control surface may be
considered, but it should also evaluate appropriate AMD and Intel GPU
power/control options rather than being NVIDIA-only.

## System

- OS: Bazzite Linux (portable/test media)
- GPUs:
  - 4× NVIDIA RTX PRO 6000 Blackwell Server Edition
- Driver:
  - NVIDIA Driver 595.71.05
- CUDA:
  - CUDA 13.2

---

# What Was Done

## 1. Verified GPUs

Command:

```bash
nvidia-smi
```

This confirmed:
- all 4 GPUs were detected
- default power cap was 600 W
- persistence mode was disabled

---

## 2. Enabled Persistence Mode (Temporary)

Command:

```bash
sudo nvidia-smi -pm 1
```

Effect:
- enabled legacy persistence mode for all GPUs
- runtime-only setting
- does NOT survive reboot unless a service/script is created

---

## 3. Lowered Power Limit to 450 W

Command:

```bash
sudo nvidia-smi -pl 450
```

Effect:
- changed software power cap from 600 W → 450 W
- applied to all GPUs
- temporary/runtime-only
- resets after reboot

---

## 4. Verified New Power Limits

Command:

```bash
nvidia-smi --query-gpu=index,name,power.limit,power.default_limit,power.max_limit --format=csv
```

Observed:
- all GPUs set to 450 W
- default limit still reported as 600 W
- max limit remained 600 W

---

## 5. Tested NVIDIA Persistence Daemon

Enabled temporarily:

```bash
sudo systemctl enable --now nvidia-persistenced
```

Then disabled again:

```bash
sudo systemctl disable --now nvidia-persistenced
```

Result:
- no persistent service remains enabled
- no permanent startup configuration was created

---

# Current State

Current configuration is TEMPORARY ONLY.

Nothing permanent was written to:
- GPU firmware/VBIOS
- boot configuration
- startup scripts
- systemd custom services

Everything will reset automatically after reboot/shutdown.

---

# How To Restore Defaults Immediately

## Restore Default 600 W Power Limit

Command:

```bash
sudo nvidia-smi -pl 600
```

Or per GPU:

```bash
sudo nvidia-smi -i 0 -pl 600
sudo nvidia-smi -i 1 -pl 600
sudo nvidia-smi -i 2 -pl 600
sudo nvidia-smi -i 3 -pl 600
```

---

## Disable Persistence Mode

Command:

```bash
sudo nvidia-smi -pm 0
```

---

## Verify Defaults Were Restored

Command:

```bash
nvidia-smi --query-gpu=index,persistence_mode,power.limit --format=csv
```

Expected output:
- Persistence mode: Disabled
- Power limit: 600.00 W

---

# Important Notes

These settings are runtime-only unless:
- custom systemd services are created
- shell startup scripts are added
- udev rules are added
- boot configuration is modified

No such persistent configuration was created during this session.

A simple reboot would also restore defaults automatically.
