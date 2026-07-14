#!/usr/bin/env bash
set -u

# Bazzite / Fedora Atomic companion probe for Linux Validation Suite.
# This script runs the generic sensor probe when available, then appends
# Bazzite-specific context that helps explain immutable OS, layered packages,
# Steam Deck / handheld quirks, containers, and GPU tooling availability.

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
  bash probe_bazzite_sensor_points.sh [output_dir] [--sudo] [--include-ids]

Examples:
  bash probe_bazzite_sensor_points.sh
  bash probe_bazzite_sensor_points.sh /tmp/lvs_bazzite_probe
  bash probe_bazzite_sensor_points.sh sensor_probe_logs --sudo

Notes:
  Keep probe_linux_sensor_points.sh in the same folder when possible. This
  companion script runs the generic probe first, then appends Bazzite-specific
  details to the same log folder.

  --sudo        Runs extra read-only commands if passwordless sudo is available.
                The script will not prompt for a password.
  --include-ids Includes DMI serial/UUID-like fields through the generic probe.
                By default those are redacted.
USAGE
      exit 0
      ;;
  esac
done

if [[ "$LOG_ROOT" == "--sudo" || "$LOG_ROOT" == "--include-ids" ]]; then
  LOG_ROOT="sensor_probe_logs"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
GENERIC_PROBE="$SCRIPT_DIR/probe_linux_sensor_points.sh"

timestamp="$(date '+%Y-%m-%d_%H-%M-%S')"
host="$(hostname 2>/dev/null || echo unknown-host)"

generic_args=("$LOG_ROOT")
[[ "$USE_SUDO" -eq 1 ]] && generic_args+=("--sudo")
[[ "$INCLUDE_IDS" -eq 1 ]] && generic_args+=("--include-ids")

if [[ -x "$GENERIC_PROBE" || -f "$GENERIC_PROBE" ]]; then
  bash "$GENERIC_PROBE" "${generic_args[@]}"
  latest_dir="$(find "$LOG_ROOT" -maxdepth 1 -type d -name "*_${host}" -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}')"
  if [[ -z "${latest_dir:-}" ]]; then
    latest_dir="${LOG_ROOT%/}/${timestamp}_${host}"
    mkdir -p "$latest_dir"
  fi
else
  latest_dir="${LOG_ROOT%/}/${timestamp}_${host}"
  mkdir -p "$latest_dir"
fi

extra_log="$latest_dir/bazzite_probe_${timestamp}_${host}.log"
exec > >(tee "$extra_log") 2>&1

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
    timeout 25s "$@" || printf '[exit %s]\n' "$?"
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

read_one_line() {
  local path="$1"
  if [[ -r "$path" && -f "$path" ]]; then
    printf '%s=' "$path"
    tr -d '\000' < "$path" 2>/dev/null | head -c 500 | tr '\n' ' '
    printf '\n'
  elif [[ -e "$path" ]]; then
    printf '%s=<unreadable>\n' "$path"
  else
    printf '%s=<missing>\n' "$path"
  fi
}

section "Bazzite Probe Metadata"
printf 'Bazzite extra log: %s\n' "$extra_log"
printf 'Combined folder: %s\n' "$latest_dir"
printf 'Generic probe found: %s\n' "$([[ -f "$GENERIC_PROBE" ]] && echo yes || echo no)"
printf 'Timestamp: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
printf 'Sudo extras: %s\n' "$([[ "$USE_SUDO" -eq 1 ]] && echo requested || echo disabled)"

section "Bazzite / Fedora Atomic Identity"
[[ -r /etc/os-release ]] && cat /etc/os-release
read_one_line /run/ostree-booted
read_one_line /etc/fedora-release
read_one_line /etc/redhat-release
run_cmd_if_present bootc "bootc status" bootc status
run_cmd_if_present rpm-ostree "rpm-ostree status" rpm-ostree status
run_cmd_if_present ujust "ujust list" ujust --list

section "Layered Packages And Relevant RPMs"
run_cmd_if_present rpm "GPU/sensor RPM inventory (filtered)" bash -c 'rpm -qa | grep -Ei "(nvidia|cuda|intel-gpu|mesa|vulkan|opencl|ocl|rocm|hip|amdgpu|radeon|lm_sensors|sensors|hwdata|pciutils|glx|egl|gamescope|mangohud)" | sort || true'
run_cmd_if_present rpm "intel-gpu-tools package" rpm -q intel-gpu-tools
run_cmd_if_present rpm "lm_sensors package" rpm -q lm_sensors
run_cmd_if_present rpm "vulkan-tools package" rpm -q vulkan-tools
run_cmd_if_present rpm "mesa vulkan/opencl packages" rpm -qa 'mesa*' 'vulkan*' '*OpenCL*' '*opencl*'
run_cmd_if_present rpm "NVIDIA packages" rpm -qa '*nvidia*' '*akmod*'
run_cmd_if_present rpm "ROCm packages" rpm -qa '*rocm*' '*hip*'

section "Flatpak / Container Context"
run_cmd_if_present flatpak "flatpak list" flatpak list --columns=application,origin,installation,version
run_cmd_if_present distrobox "distrobox list" distrobox list
run_cmd_if_present podman "podman host summary" bash -c 'podman info --format "{{.Host.OCIRuntime.Name}} {{.Host.OCIRuntime.Version}}; cgroup={{.Host.CgroupVersion}}; rootless={{.Host.Security.Rootless}}" 2>/dev/null || podman info'
run_cmd_if_present podman "podman containers" podman ps -a

section "Handheld / Deck / Ally Relevant Platform Paths"
for path in \
  /sys/class/power_supply/* \
  /sys/class/hwmon/hwmon* \
  /sys/class/leds/* \
  /sys/devices/platform/* \
  /sys/class/backlight/*; do
  [[ -e "$path" ]] && printf '%s\n' "$path"
done

subsection "power_supply details"
for supply in /sys/class/power_supply/*; do
  [[ -d "$supply" ]] || continue
  printf '\n[%s]\n' "$supply"
  for file in type manufacturer model_name status health capacity charge_* energy_* power_* voltage_* current_* temp technology cycle_count scope online present usb_type; do
    for path in "$supply"/$file; do
      [[ -e "$path" ]] && read_one_line "$path"
    done
  done
done

subsection "platform driver/module clues"
find /sys/devices/platform -maxdepth 3 \( \
  -iname '*asus*' -o -iname '*ally*' -o -iname '*steam*' -o -iname '*deck*' -o \
  -iname '*ayaneo*' -o -iname '*legion*' -o -iname '*handheld*' -o -iname '*amd*' -o \
  -iname '*gpu*' -o -iname '*fan*' -o -iname '*thermal*' \
\) -print 2>/dev/null | sort

section "Hybrid Graphics / Laptop GPU Mode"
for path in \
  /sys/devices/platform/asus-nb-wmi/dgpu_disable \
  /sys/devices/platform/asus-nb-wmi/gpu_mux_mode \
  /sys/devices/platform/asus-nb-wmi/throttle_thermal_policy \
  /sys/firmware/acpi/platform_profile \
  /sys/firmware/acpi/platform_profile_choices; do
  read_one_line "$path"
done
run_cmd_if_present supergfxctl "supergfxctl current graphics mode" supergfxctl -g
run_cmd_if_present supergfxctl "supergfxctl supported graphics modes" supergfxctl -s
run_cmd_if_present asusctl "asusctl command help" asusctl --help
run_cmd_if_present asusctl "asusctl profile help" asusctl profile --help
run_cmd_if_present switcherooctl "switcherooctl list" switcherooctl list

section "Perf / CAP_PERFMON / Intel GPU Tool Permissions"
read_one_line /proc/sys/kernel/perf_event_paranoid
run_cmd_if_present getcap "intel_gpu_top capabilities" getcap "$(command -v intel_gpu_top 2>/dev/null || echo /usr/bin/intel_gpu_top)"
run_cmd_if_present intel_gpu_top "intel_gpu_top -L" intel_gpu_top -L
run_cmd_if_present intel_gpu_top "intel_gpu_top JSON sample" intel_gpu_top -J -s 500 -n 2 -o -
run_sudo_if_available "sudo intel_gpu_top JSON sample" intel_gpu_top -J -s 500 -n 2 -o -

section "GPU Stack Quick Checks"
run_cmd_if_present vulkaninfo "vulkaninfo --summary" vulkaninfo --summary
run_cmd_if_present clinfo "clinfo first 120 lines" bash -c 'clinfo | sed -n "1,120p"'
run_cmd_if_present glxinfo "glxinfo -B" glxinfo -B
run_cmd_if_present eglinfo "eglinfo first 200 lines" bash -c 'eglinfo | sed -n "1,200p"'
run_cmd_if_present nvidia-smi "nvidia-smi query" nvidia-smi --query-gpu=index,pci.bus_id,name,driver_version,pstate,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,memory.total,memory.used,clocks.gr,clocks.mem --format=csv,noheader,nounits
run_cmd_if_present nvidia-smi "nvidia-smi temperature memory query" nvidia-smi --query-gpu=index,pci.bus_id,name,temperature.gpu,temperature.memory --format=csv,noheader,nounits
run_cmd_if_present nvidia-smi "nvidia-smi supported query fields" nvidia-smi --help-query-gpu
run_cmd_if_present nvidia-smi "nvidia-smi temperature detail" nvidia-smi -q -d TEMPERATURE

section "Bazzite Probe Complete"
printf 'Generic probe log folder: %s\n' "$latest_dir"
printf 'Bazzite extra log: %s\n' "$extra_log"
