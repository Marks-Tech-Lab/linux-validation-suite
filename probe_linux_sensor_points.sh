#!/usr/bin/env bash
set -u

# Linux Validation Suite sensor discovery probe.
# Designed for openSUSE Tumbleweed, but intentionally uses common Linux tools
# and sysfs paths so it is useful on Fedora/Ubuntu/Debian-derived hosts too.

LOG_ROOT="${1:-sensor_probe_logs}"
USE_SUDO=0
INCLUDE_IDS=0

for arg in "$@"; do
  case "$arg" in
    --sudo) USE_SUDO=1 ;;
    --include-ids) INCLUDE_IDS=1 ;;
    --help|-h)
      cat <<'USAGE'
Usage:
  bash probe_linux_sensor_points.sh [output_dir] [--sudo] [--include-ids]

Examples:
  bash probe_linux_sensor_points.sh
  bash probe_linux_sensor_points.sh /tmp/lvs_sensor_probe
  bash probe_linux_sensor_points.sh sensor_probe_logs --sudo

Notes:
  --sudo        Runs extra read-only commands if passwordless sudo is available.
                The script will not prompt for a password.
  --include-ids Includes DMI serial/UUID-like fields. By default those are
                redacted because they are not needed for sensor mapping.
USAGE
      exit 0
      ;;
  esac
done

if [[ "$LOG_ROOT" == "--sudo" || "$LOG_ROOT" == "--include-ids" ]]; then
  LOG_ROOT="sensor_probe_logs"
fi

timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
host="$(hostname 2>/dev/null || echo unknown-host)"
out_dir="${LOG_ROOT%/}/${timestamp}_${host}"
mkdir -p "$out_dir"
log_file="$out_dir/sensor_probe_${timestamp}_${host}.log"

exec > >(tee "$log_file") 2>&1

section() {
  printf '\n\n========== %s ==========\n' "$*"
}

subsection() {
  printf '\n---- %s ----\n' "$*"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

run_cmd() {
  local label="$1"
  shift
  subsection "$label"
  printf '$'
  printf ' %q' "$@"
  printf '\n'
  if have timeout; then
    timeout 20s "$@" || printf '[exit %s]\n' "$?"
  else
    "$@" || printf '[exit %s]\n' "$?"
  fi
}

run_cmd_if_present() {
  local tool="$1"
  local label="$2"
  shift 2
  if have "$tool"; then
    run_cmd "$label" "$@"
  else
    subsection "$label"
    printf '%s: missing\n' "$tool"
  fi
}

run_sudo_if_available() {
  local label="$1"
  shift
  subsection "$label"
  if [[ "$(id -u 2>/dev/null || echo 1)" -eq 0 ]]; then
    printf '$'
    printf ' %q' "$@"
    printf '\n'
    if have timeout; then
      timeout 25s "$@" || printf '[exit %s]\n' "$?"
    else
      "$@" || printf '[exit %s]\n' "$?"
    fi
    return
  fi
  if [[ "$USE_SUDO" -ne 1 ]]; then
    printf 'skipped; rerun with --sudo for this read-only probe\n'
    return
  fi
  if ! have sudo; then
    printf 'sudo: missing\n'
    return
  fi
  if ! sudo -n true >/dev/null 2>&1; then
    printf 'sudo is not available without prompting; skipped\n'
    return
  fi
  printf '$ sudo'
  printf ' %q' "$@"
  printf '\n'
  if have timeout; then
    timeout 25s sudo -n "$@" || printf '[exit %s]\n' "$?"
  else
    sudo -n "$@" || printf '[exit %s]\n' "$?"
  fi
}

stat_line() {
  local path="$1"
  if [[ -e "$path" ]]; then
    stat -Lc '%A %U:%G %s bytes %n' "$path" 2>/dev/null || ls -ld "$path" 2>/dev/null
  else
    printf 'missing %s\n' "$path"
  fi
}

read_one_line() {
  local path="$1"
  stat_line "$path"
  if [[ -r "$path" && -f "$path" ]]; then
    local value
    value="$(tr -d '\000' < "$path" 2>/dev/null | head -c 400)"
    printf '  value: %s\n' "${value//$'\n'/ }"
  elif [[ -e "$path" ]]; then
    printf '  value: <unreadable>\n'
  fi
}

read_small_file() {
  local path="$1"
  if [[ -r "$path" && -f "$path" ]]; then
    printf '%s=' "$path"
    tr -d '\000' < "$path" 2>/dev/null | head -c 400 | tr '\n' ' '
    printf '\n'
  elif [[ -e "$path" ]]; then
    printf '%s=<unreadable>\n' "$path"
  fi
}

safe_find() {
  local base="$1"
  shift
  if [[ -d "$base" ]]; then
    find "$base" "$@" 2>/dev/null | sort
  fi
}

section "Probe Metadata"
printf 'Log folder: %s\n' "$out_dir"
printf 'Log file: %s\n' "$log_file"
printf 'Timestamp: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
printf 'User: %s\n' "$(id 2>/dev/null || true)"
printf 'Shell: %s\n' "${SHELL:-unknown}"
printf 'Sudo extras: %s\n' "$([[ "$USE_SUDO" -eq 1 ]] && echo requested || echo disabled)"
printf 'Include serials/UUIDs: %s\n' "$([[ "$INCLUDE_IDS" -eq 1 ]] && echo yes || echo no)"

section "OS And Kernel"
[[ -r /etc/os-release ]] && cat /etc/os-release
run_cmd "uname" uname -a
read_one_line /proc/cmdline
run_cmd_if_present lscpu "lscpu" lscpu
run_cmd_if_present lscpu "lscpu JSON" lscpu -J
run_cmd_if_present lsmem "lsmem" lsmem
run_cmd_if_present free "free -h" free -h
run_cmd_if_present lsmod "kernel modules" lsmod

section "CPU Topology / Heterogeneous Core Hints"
subsection "CPU topology summary"
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
  [[ -d "$cpu" ]] || continue
  printf '\n[%s]\n' "$cpu"
  for path in \
    "$cpu"/online \
    "$cpu"/cpu_capacity \
    "$cpu"/core_type \
    "$cpu"/topology/core_type \
    "$cpu"/topology/physical_package_id \
    "$cpu"/topology/core_id \
    "$cpu"/topology/thread_siblings_list \
    "$cpu"/topology/core_siblings_list \
    "$cpu"/acpi_cppc/highest_perf \
    "$cpu"/acpi_cppc/nominal_perf \
    "$cpu"/acpi_cppc/lowest_nonlinear_perf \
    "$cpu"/cpufreq/scaling_cur_freq \
    "$cpu"/cpufreq/cpuinfo_max_freq \
    "$cpu"/cpufreq/base_frequency \
    "$cpu"/cpufreq/bios_limit; do
    [[ -e "$path" ]] && read_one_line "$path"
  done
done
subsection "CPU capacity and perf files"
safe_find /sys/devices/system/cpu -type f \( \
  -name cpu_capacity -o -name core_type -o -name highest_perf -o -name nominal_perf -o \
  -name cpuinfo_max_freq -o -name base_frequency -o -name thread_siblings_list \
\) | head -n 2000

section "Tool Availability"
for tool in sensors lspci lsusb lscpu lsmem lsblk smartctl nvme dmidecode decode-dimms i2cdetect i2cdump lshw inxi vulkaninfo clinfo glxinfo eglinfo nvidia-smi rocm-smi radeontop intel_gpu_top ipmitool ipmi-sensors ipmimonitoring bmc-info modinfo; do
  if have "$tool"; then
    printf '%-18s %s\n' "$tool" "$(command -v "$tool")"
  else
    printf '%-18s missing\n' "$tool"
  fi
done

section "DMI And Board Identity"
dmi_fields=(
  bios_vendor bios_version bios_date
  sys_vendor product_name product_version
  board_vendor board_name board_version
  chassis_vendor chassis_type chassis_version
)
if [[ "$INCLUDE_IDS" -eq 1 ]]; then
  dmi_fields+=(product_serial product_uuid board_serial chassis_serial)
fi
for field in "${dmi_fields[@]}"; do
  read_one_line "/sys/class/dmi/id/$field"
done
if [[ "$INCLUDE_IDS" -ne 1 ]]; then
  printf 'Serial/UUID DMI fields redacted. Rerun with --include-ids if you explicitly need them.\n'
fi
run_sudo_if_available "dmidecode baseboard/bios/system" dmidecode -t baseboard -t bios -t system
if [[ "$INCLUDE_IDS" -eq 1 ]]; then
  run_sudo_if_available "dmidecode memory devices" dmidecode -t memory
else
  run_sudo_if_available "dmidecode memory devices (serials redacted)" bash -c "dmidecode -t memory | sed -E 's/^([[:space:]]*(Serial Number|Asset Tag):).*/\\1 <redacted>/'"
fi

section "Memory SPD / DIMM Identity"
run_cmd_if_present decode-dimms "decode-dimms" decode-dimms
run_sudo_if_available "sudo decode-dimms" decode-dimms
run_cmd_if_present lshw "lshw memory class" lshw -class memory
run_cmd_if_present inxi "inxi memory" inxi -mxx
subsection "i2c SPD-like devices"
for device in /sys/bus/i2c/devices/*; do
  [[ -d "$device" ]] || continue
  name="$(cat "$device/name" 2>/dev/null || true)"
  case "${name,,}" in
    *spd*|*ee1004*|*jc42*)
      printf '\n[%s]\n' "$device"
      read_one_line "$device/name"
      read_one_line "$device/modalias"
      stat_line "$device/eeprom"
      if [[ -r "$device/eeprom" ]]; then
        printf 'eeprom hexdump first 384 bytes:\n'
        if have xxd; then
          xxd -g 1 -l 384 "$device/eeprom" 2>/dev/null || true
        elif have od; then
          od -An -tx1 -N384 "$device/eeprom" 2>/dev/null || true
        fi
      fi
      for path in "$device"/hwmon/hwmon* "$device"/driver "$device"/of_node; do
        [[ -e "$path" ]] && stat_line "$path"
      done
      ;;
  esac
done

section "PCI And USB Hardware"
run_cmd_if_present lspci "lspci -nnk" lspci -nnk
run_cmd_if_present lspci "lspci display devices verbose" lspci -Dnnvv -d '::0300'
run_cmd_if_present lspci "lspci 3D/display class devices" lspci -Dnnvv -d '::0302'
run_cmd_if_present lsusb "lsusb" lsusb
run_cmd_if_present lsblk "lsblk" lsblk -o NAME,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,MOUNTPOINTS

section "Storage Inventory / SMART / NVMe"
run_cmd_if_present lsblk "lsblk JSON storage inventory" lsblk -J -O
run_cmd_if_present nvme "nvme list" nvme list
for dev in /dev/nvme*n1 /dev/sd? /dev/hd? /dev/mmcblk?; do
  [[ -e "$dev" ]] || continue
  subsection "$dev"
  run_cmd_if_present smartctl "smartctl -i $dev" smartctl -i "$dev"
  run_cmd_if_present smartctl "smartctl -A $dev" smartctl -A "$dev"
  if [[ "$dev" == /dev/nvme* ]]; then
    run_cmd_if_present nvme "nvme id-ctrl $dev" nvme id-ctrl "$dev"
    run_cmd_if_present nvme "nvme smart-log $dev" nvme smart-log "$dev"
  fi
done

section "Loaded Sensor-Relevant Modules"
for module in k10temp coretemp nct6775 it87 asus_ec_sensors asus_wmi asus_nb_wmi asus_armoury spd5118 jc42 ee1004 i2c_piix4 i2c_i801 i2c_smbus ipmi_si ipmi_devintf ipmi_msghandler amdgpu radeon nouveau nvidia nvidia_drm i915 xe; do
  if [[ -d "/sys/module/$module" ]]; then
    printf '%s loaded\n' "$module"
    [[ -r "/sys/module/$module/version" ]] && read_small_file "/sys/module/$module/version"
  else
    printf '%s not-loaded\n' "$module"
  fi
done
run_cmd_if_present modinfo "modinfo common sensor modules" modinfo k10temp coretemp nct6775 it87 asus_ec_sensors spd5118 jc42 ipmi_si ipmi_devintf ipmi_msghandler amdgpu nvidia i915 xe

section "lm-sensors Output"
run_cmd_if_present sensors "sensors" sensors
run_cmd_if_present sensors "sensors -u" sensors -u

section "IPMI / BMC Sensors"
subsection "IPMI device nodes and modules"
for path in /dev/ipmi* /dev/ipmi/* /sys/class/ipmi/* /sys/module/ipmi_*; do
  [[ -e "$path" ]] && stat_line "$path"
done
run_cmd_if_present ipmitool "ipmitool sensor" ipmitool sensor
run_cmd_if_present ipmitool "ipmitool sdr elist full" ipmitool sdr elist full
run_cmd_if_present ipmitool "ipmitool sdr type Temperature" ipmitool sdr type Temperature
run_cmd_if_present ipmitool "ipmitool fru" ipmitool fru
run_sudo_if_available "sudo ipmitool sensor" ipmitool sensor
run_sudo_if_available "sudo ipmitool sdr elist full" ipmitool sdr elist full
run_sudo_if_available "sudo ipmitool sdr type Temperature" ipmitool sdr type Temperature
run_cmd_if_present ipmi-sensors "freeipmi ipmi-sensors" ipmi-sensors
run_cmd_if_present ipmi-sensors "freeipmi ipmi-sensors temperature records" ipmi-sensors --sensor-types=temperature
run_cmd_if_present ipmimonitoring "freeipmi ipmimonitoring" ipmimonitoring
run_cmd_if_present bmc-info "freeipmi bmc-info" bmc-info

section "hwmon Sysfs Full Sensor Map"
shopt -s nullglob
for hwmon in /sys/class/hwmon/hwmon*; do
  subsection "$hwmon"
  read_one_line "$hwmon/name"
  printf 'resolved path: %s\n' "$(readlink -f "$hwmon" 2>/dev/null || true)"
  [[ -e "$hwmon/device" ]] && printf 'device path: %s\n' "$(readlink -f "$hwmon/device" 2>/dev/null || true)"
  [[ -r "$hwmon/uevent" ]] && sed 's/^/  uevent: /' "$hwmon/uevent"
  for path in "$hwmon"/temp* "$hwmon"/power* "$hwmon"/energy* "$hwmon"/fan* "$hwmon"/in* "$hwmon"/curr* "$hwmon"/pwm* "$hwmon"/freq* "$hwmon"/humidity*; do
    [[ -e "$path" ]] || continue
    read_one_line "$path"
  done
done

section "Thermal Zones"
for zone in /sys/class/thermal/thermal_zone*; do
  subsection "$zone"
  read_one_line "$zone/type"
  read_one_line "$zone/temp"
  for path in "$zone"/trip_point_*; do
    [[ -e "$path" ]] && read_one_line "$path"
  done
done

section "Powercap / RAPL / Energy Counters"
for cap in /sys/class/powercap/* /sys/devices/virtual/powercap/*; do
  [[ -e "$cap" ]] || continue
  subsection "$cap"
  printf 'resolved path: %s\n' "$(readlink -f "$cap" 2>/dev/null || true)"
  for path in "$cap"/name "$cap"/enabled "$cap"/energy_uj "$cap"/max_energy_range_uj "$cap"/power_uw "$cap"/constraint_*; do
    [[ -e "$path" ]] && read_one_line "$path"
  done
done

section "DRM GPU Sysfs Map"
for card in /sys/class/drm/card[0-9]*; do
  [[ -d "$card/device" ]] || continue
  subsection "$card"
  device="$card/device"
  printf 'device path: %s\n' "$(readlink -f "$device" 2>/dev/null || true)"
  printf 'driver: %s\n' "$(readlink -f "$device/driver" 2>/dev/null || true)"
  for path in "$device"/vendor "$device"/device "$device"/subsystem_vendor "$device"/subsystem_device "$device"/revision "$device"/class "$device"/uevent "$device"/boot_vga; do
    [[ -e "$path" ]] && read_one_line "$path"
  done
  for path in "$device"/gpu_busy_percent "$device"/mem_busy_percent "$device"/mem_info_* "$device"/pp_dpm_* "$device"/pp_cur_state "$device"/power_dpm_* "$device"/power_profile_mode "$device"/current_link_speed "$device"/current_link_width "$device"/max_link_speed "$device"/max_link_width "$device"/numa_node; do
    [[ -e "$path" ]] && read_one_line "$path"
  done
  for hw in "$device"/hwmon/hwmon*; do
    [[ -d "$hw" ]] || continue
    subsection "$card hwmon $(basename "$hw")"
    read_one_line "$hw/name"
    for path in "$hw"/temp* "$hw"/power* "$hw"/energy* "$hw"/fan* "$hw"/in* "$hw"/curr* "$hw"/pwm* "$hw"/freq*; do
      [[ -e "$path" ]] && read_one_line "$path"
    done
  done
done

section "Vulkan / OpenCL / GL Discovery"
run_cmd_if_present vulkaninfo "vulkaninfo --summary" vulkaninfo --summary
run_cmd_if_present clinfo "clinfo summary" clinfo
run_cmd_if_present glxinfo "glxinfo -B" glxinfo -B
run_cmd_if_present eglinfo "eglinfo" eglinfo

section "Vendor GPU Tools"
run_cmd_if_present nvidia-smi "nvidia-smi query" nvidia-smi --query-gpu=index,pci.bus_id,name,driver_version,pstate,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,memory.total,memory.used,clocks.gr,clocks.mem --format=csv,noheader,nounits
run_cmd_if_present nvidia-smi "nvidia-smi temperature memory query" nvidia-smi --query-gpu=index,pci.bus_id,name,temperature.gpu,temperature.memory --format=csv,noheader,nounits
run_cmd_if_present nvidia-smi "nvidia-smi supported query fields" nvidia-smi --help-query-gpu
run_cmd_if_present nvidia-smi "nvidia-smi temperature detail" nvidia-smi -q -d TEMPERATURE
run_cmd_if_present nvidia-smi "nvidia-smi -q" nvidia-smi -q
run_cmd_if_present rocm-smi "rocm-smi" rocm-smi
run_cmd_if_present radeontop "radeontop dump" radeontop -d - -l 1
run_cmd_if_present intel_gpu_top "intel_gpu_top json sample" intel_gpu_top -J -s 1000 -o -

section "Sensor-Like Files Outside hwmon"
subsection "selected sysfs names/labels containing thermal, power, vrm, voltage hints"
safe_find /sys -type f \( \
  -iname '*temp*' -o -iname '*power*' -o -iname '*energy*' -o -iname '*volt*' -o \
  -iname '*vcore*' -o -iname '*vrm*' -o -iname '*mos*' -o -iname '*fan*' -o \
  -iname '*busy*' -o -iname '*mem_info*' \
\) | grep -E '/(hwmon|thermal|powercap|drm|platform|i2c|pci|devices)/' | head -n 2000

section "Permission Snapshot For Likely Telemetry Files"
for path in \
  /sys/class/hwmon/hwmon*/* \
  /sys/class/powercap/*/* \
  /sys/devices/virtual/powercap/*/* \
  /sys/class/drm/card[0-9]*/device/gpu_busy_percent \
  /sys/class/drm/card[0-9]*/device/mem_busy_percent \
  /sys/class/drm/card[0-9]*/device/mem_info_* \
  /sys/class/drm/card[0-9]*/device/hwmon/hwmon*/*; do
  [[ -e "$path" ]] && stat_line "$path"
done

section "Probe Complete"
printf 'Saved log: %s\n' "$log_file"
printf 'Folder: %s\n' "$out_dir"
