# Telemetry Probe Notes

These public engineering provenance notes summarize concrete sensor evidence
reviewed across these generic probe categories:

- repeated x86_64 multi-GPU lab probe sessions
- an ARM64 Snapdragon X Plus laptop probe

The observations document hardware- and driver-family evidence used during
telemetry development. They are not a complete support matrix or a promise of
support coverage for any specific platform or release.

The resulting telemetry changes are intentionally additive. They do not change
thresholds, pass/fail behavior, parsed importer-facing fields, CLI/TUI behavior,
report wording, or QA payload contracts. Existing consumers can ignore unknown
raw/source-map/capability fields.

## Additive Evidence Now Captured

- DDR5 DIMM temperatures from `spd5118` hwmon devices as optional memory module
  temperature evidence.
- NVIDIA fan speed from `nvidia-smi` as `gpu_N_fan_percent` when available.
- NVIDIA clocks/throttle event reason evidence from `nvidia-smi`, including
  idle, applications clocks, software power cap, hardware slowdown, hardware
  thermal slowdown, hardware power brake, sync boost, and software thermal
  slowdown reason fields.
- AMD GPU voltage evidence for clearly labeled `vddgfx` and `vddnb` hwmon
  voltage inputs as `gpu_N_vddgfx_v` and `gpu_N_vddnb_v`.
- NVMe secondary temperature sensors as optional
  `storage_drive_N_sensor_1_temp_c`, `storage_drive_N_sensor_2_temp_c`, etc.,
  while preserving existing composite storage temperature behavior.
- Realtek wired NIC temperature from `r8169` hwmon devices as optional
  `nic_N_temp_c` evidence.
- Intel Wi-Fi temperature from `iwlwifi` hwmon/thermal-zone evidence as optional
  `wifi_N_temp_c`.
- Qualcomm/Atheros Wi-Fi temperature from clearly labeled `ath11k` hwmon
  evidence as optional `wifi_N_temp_c`.
- Gigabyte WMI board thermal values from `gigabyte_wmi` hwmon devices as
  optional `board_N_temp_c` evidence.
- PCIe link evidence for storage and GPU devices where sysfs exposes it:
  maximum/current link speed and maximum/current link width are captured as
  optional storage/GPU inventory fields and source-map evidence.

## Snapdragon Probe Notes

The Snapdragon X Plus laptop probe exposed many Qualcomm virtual thermal zones,
including CPU cluster, GPU subsystem, video/camera, AOSS/PMIC, and related
thermal-zone labels. These are useful as generic source evidence but are not
promoted into validation metrics without clearer stable component semantics.
The same probe exposed `ath11k` hwmon Wi-Fi temperature, which is now captured
through the existing optional Wi-Fi temperature evidence path. NVMe composite
temperature was already covered by existing storage telemetry.

## Not Added

- VRM/MOS telemetry: not exposed by the reviewed probes.
- Board voltage rails: not clearly exposed with stable labels in the reviewed
  probes.
- Fan RPM: skipped where the exposed ACPI fan source returned `N/A` or was
  unreadable.
- Chipset/PCH temperature: not added unless future probes expose a clearly
  labeled source.
- IPMI/BMC sensors: tools were present on one probe, but no local IPMI/BMC
  device or usable sensor records were available.
- Battery manager voltage/power/temperature and Qualcomm PMIC thermal-zone
  values from the Snapdragon probe are not promoted into validation metrics;
  they remain probe evidence until a clear downstream use exists.
- Forced Super I/O probing: intentionally not used; telemetry remains based on
  concrete exposed kernel/sysfs/tool evidence.

## Contract Notes

- All fields above are optional and absent cleanly when unsupported.
- Evidence-only fields are for troubleshooting and QA context, not validation
  policy.
- Raw telemetry/source-map/capability additions are additive only.
- Existing raw keys and parsed result/importer-facing structures remain stable.
