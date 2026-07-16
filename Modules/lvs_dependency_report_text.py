#!/usr/bin/env python3
"""Text renderers for dependency check reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def dependency_status_text(available: bool, preferred: bool = False) -> str:
    if available:
        return "OK"
    return "missing preferred" if preferred else "missing"


def dependency_item_lines(
    name: str,
    available: bool,
    *,
    detail: str = "",
    fix: str = "",
    preferred: bool = False,
) -> list[str]:
    status = dependency_status_text(available, preferred=preferred)
    line = f"  [{status}] {name}"
    if detail:
        line += f" - {detail}"
    lines = [line]
    if not available and fix:
        lines.append(f"       fix: {fix}")
    return lines


def dependency_summary_text(
    backends: Dict[str, Any],
    details: Dict[str, Any],
    capabilities: Dict[str, Any],
    drive: Dict[str, Any],
    *,
    storage_health: Optional[Dict[str, Any]] = None,
) -> str:
    def status(key: str) -> str:
        return "OK" if bool(backends.get(key)) else "missing"

    lines = [
        "Dependency / Readiness Summary",
        "==============================",
        "",
        "Suite backends:",
        f"- CPU native helper: {status('cpu_native_helper')}",
        f"- Memory native helper: {status('memory_native_helper')}",
        f"- Vulkan compute/readback: {status('python_vulkan_compute')}",
        f"- Vulkan transfer/readback: {status('python_vulkan_transfer')}",
        f"- OpenCL compute/VRAM: {status('python_opencl')}",
        f"- EGL/GLES render/readback: {status('python_egl_gles2')}",
        "",
        "External tools:",
        f"- nvidia-smi: {status('nvidia_smi')}",
        f"- intel_gpu_top: {'OK' if bool((details.get('intel_gpu_top') or {}).get('usable')) else 'missing/limited'}",
        f"- glmark2: {status('glmark2')}",
        f"- vkmark: {status('vkmark')}",
        "",
        "Telemetry:",
    ]
    for key, label in [
        ("cpu_temp_c", "CPU temp"),
        ("cpu_power_w", "CPU package power"),
        ("memory_temp_c", "DIMM temp"),
        ("gpu_temp_c", "GPU temp"),
        ("gpu_power_w", "GPU power"),
        ("gpu_busy_percent", "GPU busy"),
        ("gpu_vram_used_gb", "GPU VRAM used"),
    ]:
        cap = capabilities.get(key) if isinstance(capabilities.get(key), dict) else {}
        source = str(cap.get("source") or "")
        count = cap.get("count")
        suffix = f", count={count}" if count else ""
        lines.append(f"- {label}: {'OK' if cap.get('available') else 'missing'} ({source}{suffix})")
    storage_health = storage_health if isinstance(storage_health, dict) else {}
    if storage_health:
        lines.extend(
            [
                "",
                "Storage Health / SMART:",
                f"- Status: {storage_health.get('status') or 'unavailable'}",
                "- Coverage: "
                + f"{storage_health.get('successfully_queried_drive_count', 0)}/"
                + f"{storage_health.get('eligible_internal_drive_count', 0)} eligible internal drive(s)",
            ]
        )
    lines.extend(
        [
            "",
            "Google Drive upload:",
            f"- Ready: {'yes' if drive.get('ready') else 'no'}",
            f"- Credentials: {'OK' if drive.get('credential_exists') else 'missing'}",
            f"- Shared Drive ID: {'configured' if drive.get('shared_drive_id_configured') else 'missing'}",
        ]
    )
    missing = list(drive.get("missing") or [])
    if missing:
        lines.append("- Missing: " + ", ".join(str(item) for item in missing))
    return "\n".join(lines)


def dependency_check_detail_text(payload: Dict[str, Any]) -> str:
    execution_context = payload.get("execution_context") if isinstance(payload.get("execution_context"), dict) else {}
    helper_requested = bool(execution_context.get("privileged_helper_enabled"))
    helper_effective = bool(execution_context.get("privileged_helper_effective"))
    backends = payload.get("backends") if isinstance(payload.get("backends"), dict) else {}
    details = payload.get("backend_details") if isinstance(payload.get("backend_details"), dict) else {}
    telemetry_capabilities = (
        payload.get("telemetry_capabilities")
        if isinstance(payload.get("telemetry_capabilities"), dict)
        else {}
    )
    memory_modules = payload.get("memory_modules") if isinstance(payload.get("memory_modules"), list) else []
    lines = [
        "",
        "Dependency Check",
        "This is a quick machine-readiness summary. Dry Run / Diagnostics still shows profile-specific details.",
        "Execution: "
        + f"user={execution_context.get('user') or '-'}, "
        + f"uid={execution_context.get('effective_uid')}, "
        + f"root={'yes' if execution_context.get('is_root') else 'no'}, "
        + f"python={execution_context.get('python_executable')}",
        "Privileged helper: "
        + ("enabled" if helper_requested else "disabled")
        + (
            ", ready"
            if helper_effective
            else ", not ready"
            if helper_requested
            else ""
        ),
    ]

    cpu_helper = details.get("cpu_native_helper", {})
    memory_helper = details.get("memory_native_helper", {})
    lines.extend(
        dependency_item_lines(
            "CPU native helper",
            bool(backends.get("cpu_native_helper")),
            detail=str(cpu_helper.get("path") or cpu_helper.get("reason") or ""),
            fix="install gcc/build-essential and keep native/cpu_stress_helper.c available; Python fallback can still run basic CPU load",
            preferred=True,
        )
    )
    lines.extend(
        dependency_item_lines(
            "Memory native helper",
            bool(backends.get("memory_native_helper")),
            detail=str(memory_helper.get("path") or memory_helper.get("reason") or ""),
            fix="install gcc/build-essential and keep native/memory_stress_helper.c available; Python fallback can still run basic RAM load",
            preferred=True,
        )
    )
    lines.extend(
        dependency_item_lines(
            "stress-ng",
            bool(backends.get("stress_ng")),
            detail="optional external CPU/RAM fallback",
            fix="install stress-ng if you want that external fallback path",
            preferred=True,
        )
    )

    lines.append("")
    lines.append("GPU Test Backends")
    egl = details.get("python_egl_gles2", {})
    egl_available = bool(backends.get("python_egl_gles2"))
    egl_detail = str(egl.get("renderer") or "")
    if not egl_available and egl.get("reason"):
        egl_detail = str(egl.get("reason") or "")
    lines.extend(
        dependency_item_lines(
            "Suite EGL/GLES render/readback",
            egl_available,
            detail=egl_detail,
            fix="install Mesa EGL/GLES libraries and make sure the session exposes a hardware renderer, not llvmpipe",
        )
    )
    opencl = details.get("python_opencl", {})
    opencl_context = str(opencl.get("selected_context") or "")
    opencl_detail = str(opencl.get("reason") or "")
    opencl_devices = list(opencl.get("devices") or [])
    if opencl.get("available"):
        opencl_detail = f"{len(opencl_devices)} GPU device(s)"
        if opencl_context:
            opencl_detail += f", context={opencl_context}"
        selected_env = opencl.get("selected_env") or {}
        if selected_env:
            opencl_detail += f", env={selected_env}"
    lines.extend(
        dependency_item_lines(
            "Suite OpenCL compute/VRAM",
            bool(backends.get("python_opencl")),
            detail=opencl_detail,
            fix=(
                "install an OpenCL ICD loader and GPU runtime; the suite probes native, vendor ICD isolation, "
                "and Intel/AMD Rusticl fallbacks when available"
            ),
        )
    )
    if opencl_devices:
        lines.append("  OpenCL devices found:")
        for device in opencl_devices:
            vendor = str(device.get("vendor") or device.get("platform_vendor") or "").split("(")[0].strip()
            name = str(device.get("name") or "")
            mem_gb = int(device.get("global_mem_bytes") or 0) / (1024 ** 3)
            mem_text = f", {mem_gb:.1f}GB" if mem_gb > 0 else ""
            lines.append(f"    [{device.get('opencl_index', '?')}] {name} ({vendor}{mem_text})")
    opencl_coverage = payload.get("gpu_opencl_coverage") if isinstance(payload.get("gpu_opencl_coverage"), list) else []
    if opencl_coverage:
        lines.append("  Per-GPU OpenCL coverage:")
        for item in opencl_coverage:
            target_id = str(item.get("target_id") or "")
            name = str(item.get("name") or item.get("vendor") or "")
            if item.get("available"):
                matched_name = str(item.get("matched_device") or "")
                req_env = item.get("required_env") if isinstance(item.get("required_env"), dict) else {}
                env_parts = []
                if "OCL_ICD_VENDORS" in req_env:
                    env_parts.append(req_env["OCL_ICD_VENDORS"].rsplit("/", 1)[-1])
                if "RUSTICL_ENABLE" in req_env:
                    env_parts.append(f"RUSTICL_ENABLE={req_env['RUSTICL_ENABLE']}")
                env_note = f" ({', '.join(env_parts)})" if env_parts else ""
                lines.append(f"    OK   {target_id} ({name}) → {matched_name}{env_note}")
            else:
                lines.append(f"    MISS {target_id} ({name}) — {item.get('fix') or 'no matching OpenCL device found'}")
    vulkan_compute = details.get("python_vulkan_compute", {})
    vulkan_detail = str(vulkan_compute.get("reason") or "")
    if vulkan_compute.get("available"):
        vulkan_detail = (
            f"{vulkan_compute.get('runtime_gpu_device_count', 0)} GPU device(s), "
            + f"loader={vulkan_compute.get('loader_version') or vulkan_compute.get('library') or 'found'}"
        )
    lines.extend(
        dependency_item_lines(
            "Suite Vulkan compute/readback",
            bool(backends.get("python_vulkan_compute")),
            detail=vulkan_detail,
            fix="install Vulkan loader/tools and a non-CPU Vulkan GPU driver; keep native/vulkan_compute_worker.py available",
        )
    )
    vulkan_transfer = details.get("python_vulkan_transfer", {})
    lines.extend(
        dependency_item_lines(
            "Suite Vulkan transfer/readback",
            bool(backends.get("python_vulkan_transfer")),
            detail=str(vulkan_transfer.get("reason") or vulkan_transfer.get("worker_path") or ""),
            fix="install Vulkan loader/tools and keep native/vulkan_transfer_worker.py available",
            preferred=True,
        )
    )

    lines.append("")
    lines.append("External Compatibility / Benchmark Tools")
    external_tools = [
        ("glmark2", "glmark2", "optional benchmark/compatibility tool, not the preferred stress path", "install glmark2 only if you want external OpenGL benchmark diagnostics"),
        ("vkmark", "vkmark", "optional benchmark/compatibility tool, not the preferred stress path", "install vkmark only if you want external Vulkan benchmark diagnostics"),
        ("vkcube", "vkcube", "optional Vulkan smoke test", "install vulkan-tools if you want vkcube smoke diagnostics"),
        ("glxgears", "glxgears", "optional OpenGL smoke test", "install mesa-utils if you want glxgears smoke diagnostics"),
        ("nvidia-smi", "nvidia_smi", "only expected on NVIDIA systems", "install NVIDIA driver utilities if this machine has NVIDIA GPUs"),
    ]
    for label, key, detail, fix in external_tools:
        lines.extend(
            dependency_item_lines(
                label,
                bool(backends.get(key)),
                detail=detail,
                fix=fix,
                preferred=True,
            )
        )
    intel_gpu_top = details.get("intel_gpu_top", {})
    intel_detail = str(intel_gpu_top.get("reason") or "")
    if intel_gpu_top.get("available"):
        device_count = len(list(intel_gpu_top.get("devices") or []))
        if intel_gpu_top.get("usable"):
            usable_text = "usable"
        elif intel_gpu_top.get("list_available"):
            usable_text = "device list works, telemetry blocked"
        else:
            usable_text = "installed but not usable"
        intel_detail = f"{usable_text}, listed devices={device_count}"
        if intel_gpu_top.get("json_sample_available"):
            intel_detail += f", JSON busy sample={intel_gpu_top.get('json_sample_metrics')}"
        elif intel_gpu_top.get("list_available"):
            intel_detail += ", JSON busy sample=missing"
        if intel_gpu_top.get("reason"):
            intel_detail += f", {intel_gpu_top.get('reason')}"
    lines.extend(
        dependency_item_lines(
            "Intel GPU telemetry tool (intel_gpu_top from intel-gpu-tools)",
            bool(intel_gpu_top.get("usable")),
            detail=intel_detail,
            fix="install intel-gpu-tools; if JSON sampling is permission-denied, allow CAP_PERFMON or adjust perf security policy",
            preferred=any(str(item.get("vendor") or "").strip().lower() == "intel" for item in opencl_coverage),
        )
    )
    if intel_gpu_top.get("devices"):
        lines.append("  intel_gpu_top devices:")
        for device in intel_gpu_top.get("devices") or []:
            lines.append(f"    {device.get('raw')}")

    lines.append("")
    lines.append("Memory Identity")
    memory_identity = payload.get("memory_identity") if isinstance(payload.get("memory_identity"), dict) else {}
    lines.extend(
        dependency_item_lines(
            "DIMM manufacturer / part-number inventory",
            bool(memory_identity.get("available")),
            detail=(
                f"{memory_identity.get('identified_module_count', 0)}/"
                + f"{memory_identity.get('module_count', 0)} module(s), source={memory_identity.get('source')}"
            ),
            fix=(
                "install dmidecode or inxi; run with permission to read SMBIOS/DMI memory tables "
                "if full DIMM identity is required"
            ),
            preferred=True,
        )
    )
    for module in memory_modules:
        name_parts = [
            str(module.get("position") or f"DIMM {module.get('module_number', '')}").strip(),
            str(module.get("manufacturer") or "").strip(),
            str(module.get("part_number") or "").strip(),
            str(module.get("size") or "").strip(),
            str(module.get("base_speed") or "").strip(),
        ]
        summary = " | ".join(part for part in name_parts if part)
        if summary:
            lines.append(f"    {summary}")
    ipmi_details = details.get("ipmi_sensors", {})
    lines.extend(
        dependency_item_lines(
            "IPMI/BMC sensor tools",
            bool(ipmi_details.get("available")),
            detail=str(ipmi_details.get("reason") or ipmi_details.get("path") or ""),
            fix="install ipmitool or freeipmi if this server board exposes DIMM/DRAM temperatures only through IPMI",
            preferred=bool(ipmi_details.get("device_node_available")),
        )
    )
    if ipmi_details.get("device_nodes"):
        lines.append("  IPMI device nodes:")
        for node in ipmi_details.get("device_nodes") or []:
            lines.append(f"    {node}")

    lines.append("")
    lines.append("Storage Health / SMART")
    storage_health = payload.get("storage_health") if isinstance(payload.get("storage_health"), dict) else {}
    baseline = (
        storage_health.get("baseline_sysfs_inventory")
        if isinstance(storage_health.get("baseline_sysfs_inventory"), dict)
        else {}
    )
    lines.extend(
        dependency_item_lines(
            "Baseline sysfs storage inventory",
            bool(baseline.get("available")),
            detail=f"{baseline.get('drive_count', 0)} drive(s), source={baseline.get('source') or 'sysfs'}",
            fix="ensure /sys/block is mounted and readable",
        )
    )
    storage_tools = storage_health.get("tools") if isinstance(storage_health.get("tools"), dict) else {}
    tool_specs = (
        ("lsblk", "lsblk identity/classification", "install util-linux", False),
        ("udevadm", "udevadm identity/classification", "install systemd-udev", False),
        ("smartctl", "smartctl SMART health", "install smartmontools", True),
        ("nvme_cli", "nvme-cli NVMe health", "install nvme-cli", True),
    )
    for key, label, fix, preferred in tool_specs:
        tool = storage_tools.get(key) if isinstance(storage_tools.get(key), dict) else {}
        detail = str(tool.get("version") or tool.get("path") or "")
        lines.extend(
            dependency_item_lines(
                label,
                bool(tool.get("available")),
                detail=detail,
                fix=fix,
                preferred=preferred,
            )
        )
    storage_status = str(storage_health.get("status") or "unavailable")
    status_label = "OK" if storage_status == "available" else "N/A" if storage_status == "not_applicable" else "WARN"
    lines.append(
        f"  [{status_label}] Coverage - "
        + f"{storage_health.get('successfully_queried_drive_count', 0)}/"
        + f"{storage_health.get('eligible_internal_drive_count', 0)} eligible internal drive(s), "
        + f"internal={storage_health.get('internal_drive_count', 0)}, "
        + f"permission-limited={storage_health.get('permission_limited_count', 0)}, "
        + f"unsupported={storage_health.get('unsupported_controller_count', 0)}, status={storage_status}"
    )

    lines.append("")
    lines.append("Telemetry")
    telemetry_labels = {
        "cpu_temp_c": "CPU temperature",
        "cpu_power_w": "CPU package power",
        "cpu_clock_mhz": "CPU clock",
        "cpu_core_clock_mhz": "Per-core CPU clocks",
        "memory_temp_c": "DIMM temperature",
        "storage_temp_c": "Storage temperature",
        "memory_used_gb": "System memory usage",
        "gpu_temp_c": "GPU temperature",
        "gpu_memory_temp_c": "GPU memory temperature",
        "gpu_power_w": "GPU power",
        "gpu_clock_mhz": "GPU clock",
        "gpu_memory_clock_mhz": "GPU memory clock",
        "gpu_busy_percent": "GPU busy",
        "gpu_memory_busy_percent": "GPU memory busy",
        "gpu_vram_used_gb": "GPU VRAM used",
    }
    for key, label in telemetry_labels.items():
        capability = telemetry_capabilities.get(key, {})
        count = capability.get("count")
        count_text = f", count={count}" if count else ""
        lines.extend(
            dependency_item_lines(
                label,
                bool(capability.get("available")),
                detail=f"{capability.get('source') or ''}{count_text}",
                fix="sensor may be unsupported, hidden by permissions, or not exposed by this driver/kernel",
                preferred=key in {"cpu_power_w", "memory_temp_c", "gpu_memory_busy_percent"},
            )
        )
    gpu_matrix = ((telemetry_capabilities.get("gpu_telemetry_by_gpu") or {}).get("gpus") or [])
    if gpu_matrix:
        lines.append("  Per-GPU telemetry coverage:")
        for gpu in gpu_matrix:
            metrics = gpu.get("metrics") or {}
            available = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and detail.get("available")
            ]
            missing = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and not detail.get("available")
            ]
            target = gpu.get("slot") or gpu.get("card") or f"gpu{gpu.get('gpu_index')}"
            lines.append(
                f"    GPU {gpu.get('gpu_index')} {target} {gpu.get('vendor') or ''} {gpu.get('driver') or ''}: "
                + f"available={', '.join(available) if available else '-'}; "
                + f"missing={', '.join(missing) if missing else '-'}"
            )

    lines.append("")
    lines.append("Upload / Sync")
    drive_status = payload.get("google_drive_upload") if isinstance(payload.get("google_drive_upload"), dict) else {}
    modules = drive_status.get("python_modules") if isinstance(drive_status.get("python_modules"), dict) else {}
    missing_modules = [name for name, available in modules.items() if not available]
    detail_parts = [str(drive_status.get("credential_path") or "")]
    if missing_modules:
        detail_parts.append("missing modules: " + ", ".join(missing_modules))
    if not drive_status.get("dns_ok"):
        detail_parts.append(f"DNS issue: {drive_status.get('dns_error') or drive_status.get('dns_host')}")
    if not drive_status.get("shared_drive_id_configured"):
        detail_parts.append("shared Drive ID missing")
    lines.extend(
        dependency_item_lines(
            "Google Drive upload",
            bool(drive_status.get("ready")),
            detail="; ".join(part for part in detail_parts if part),
            fix=(
                "place google-credentials.json at the configured path, install the optional dependencies with "
                + ".venv/bin/python -m pip install -r requirements-google.txt, and share the target Drive folder "
                + "with the service account"
            ),
            preferred=True,
        )
    )
    lines.append("")
    lines.append("Current profiles can still be checked with option 4 for exact per-stage backend choices.")
    return "\n".join(lines) + "\n"


def dependency_check_summary_text(payload: Dict[str, Any], report_dir: Optional[Path] = None) -> str:
    backends = payload.get("backends") if isinstance(payload.get("backends"), dict) else {}
    details = payload.get("backend_details") if isinstance(payload.get("backend_details"), dict) else {}
    telemetry = payload.get("telemetry_capabilities") if isinstance(payload.get("telemetry_capabilities"), dict) else {}

    def status(name: str) -> str:
        return "OK" if bool(backends.get(name)) else "missing"

    lines = []
    lines.append("\nDependency Check Summary")
    lines.append("========================")
    if report_dir is not None:
        lines.append(f"Saved folder: {report_dir}")
    lines.append("Full details: dependency_check.txt")
    execution_context = payload.get("execution_context") if isinstance(payload.get("execution_context"), dict) else {}
    if execution_context:
        root_text = "yes" if execution_context.get("is_root") else "no"
        lines.append(
            "Execution: "
            + f"{execution_context.get('user') or '-'} "
            + f"(uid={execution_context.get('effective_uid')}, root={root_text})"
        )
        lines.append(
            "Privileged helper: "
            + ("enabled" if execution_context.get("privileged_helper_enabled") else "disabled")
            + (
                ", sudo prompt enabled"
                if execution_context.get("privileged_helper_enabled")
                and execution_context.get("privileged_helper_prompt_for_sudo")
                else ""
            )
        )
        if execution_context.get("privileged_helper_enabled"):
            if execution_context.get("privileged_helper_effective"):
                lines.append("Privileged helper status: ready")
            else:
                lines.append("Privileged helper status: enabled but sudo is not ready for non-interactive helper reads")
        if execution_context.get("python_executable"):
            lines.append(f"Python: {execution_context.get('python_executable')}")
    lines.append("")
    lines.append("Suite Stress Backends:")
    lines.append(f"  - CPU native helper: {status('cpu_native_helper')}")
    lines.append(f"  - Memory native helper: {status('memory_native_helper')}")
    lines.append(f"  - Vulkan compute/readback: {status('python_vulkan_compute')}")
    lines.append(f"  - Vulkan transfer/readback: {status('python_vulkan_transfer')}")
    lines.append(f"  - OpenCL compute/VRAM: {status('python_opencl')}")
    lines.append(f"  - EGL/GLES render/readback fallback: {status('python_egl_gles2')}")

    vulkan_compute = details.get("python_vulkan_compute") if isinstance(details.get("python_vulkan_compute"), dict) else {}
    if vulkan_compute:
        if vulkan_compute.get("available"):
            lines.append(
                "    Vulkan devices: "
                + str(vulkan_compute.get("runtime_gpu_device_count") or vulkan_compute.get("gpu_device_count") or 0)
            )
        elif vulkan_compute.get("reason"):
            lines.append(f"    Vulkan reason: {vulkan_compute.get('reason')}")

    opencl = details.get("python_opencl") if isinstance(details.get("python_opencl"), dict) else {}
    if opencl:
        devices = list(opencl.get("devices") or [])
        if opencl.get("available"):
            context = str(opencl.get("selected_context") or "")
            suffix = f", context={context}" if context else ""
            lines.append(f"    OpenCL devices: {len(devices)}{suffix}")
        elif opencl.get("reason"):
            lines.append(f"    OpenCL reason: {opencl.get('reason')}")

    coverage = payload.get("gpu_opencl_coverage") if isinstance(payload.get("gpu_opencl_coverage"), list) else []
    if coverage:
        missing_coverage = [item for item in coverage if isinstance(item, dict) and not item.get("available")]
        lines.append("")
        lines.append("OpenCL Target Coverage:")
        lines.append(f"  - Covered GPUs: {len(coverage) - len(missing_coverage)}/{len(coverage)}")
        for item in missing_coverage[:6]:
            target = item.get("target_id") or item.get("name") or "gpu"
            lines.append(
                f"  - Missing {target}: "
                f"{item.get('fix') or 'no matching OpenCL device found after available probes'}"
            )
        if len(missing_coverage) > 6:
            lines.append(f"  ... {len(missing_coverage) - 6} more missing OpenCL target(s)")

    intel = details.get("intel_gpu_top") if isinstance(details.get("intel_gpu_top"), dict) else {}
    if intel:
        if intel.get("usable"):
            lines.append("Intel GPU telemetry: OK")
        elif intel.get("available"):
            reason = str(intel.get("reason") or "installed but telemetry sample was not usable")
            lines.append(f"Intel GPU telemetry: partial - {reason}")
        elif intel.get("reason"):
            lines.append(f"Intel GPU telemetry: missing - {intel.get('reason')}")

    memory_identity = payload.get("memory_identity") if isinstance(payload.get("memory_identity"), dict) else {}
    if memory_identity:
        lines.append("")
        lines.append("Memory Identity:")
        lines.append(
            "  - DIMM identities: "
            + (
                "OK"
                if memory_identity.get("available")
                else "missing/permission-limited"
            )
            + f" ({memory_identity.get('identified_module_count', 0)}/{memory_identity.get('module_count', 0)} identified)"
            + f", source={memory_identity.get('source') or 'not found'}"
        )

    storage_health = payload.get("storage_health") if isinstance(payload.get("storage_health"), dict) else {}
    if storage_health:
        lines.append("")
        lines.append("Storage Health / SMART:")
        status_text = str(storage_health.get("status") or "unavailable")
        lines.append(f"  - Status: {status_text}")
        lines.append(
            "  - Coverage: "
            + f"{storage_health.get('successfully_queried_drive_count', 0)}/"
            + f"{storage_health.get('eligible_internal_drive_count', 0)} eligible internal drive(s)"
        )
        if storage_health.get("permission_limited_count"):
            lines.append(f"  - Permission-limited: {storage_health.get('permission_limited_count')}")
        if storage_health.get("unsupported_controller_count"):
            lines.append(f"  - Unsupported controllers: {storage_health.get('unsupported_controller_count')}")

    required_telemetry = (
        "cpu_temp_c",
        "cpu_power_w",
        "memory_temp_c",
        "storage_temp_c",
        "gpu_temp_c",
        "gpu_power_w",
        "gpu_busy_percent",
        "gpu_vram_used_gb",
    )
    missing_telemetry = []
    for key in required_telemetry:
        cap = telemetry.get(key) if isinstance(telemetry.get(key), dict) else {}
        if not cap.get("available"):
            missing_telemetry.append(key)
    lines.append("")
    lines.append("Telemetry:")
    lines.append(f"  - Missing/limited key sources: {', '.join(missing_telemetry) if missing_telemetry else 'none'}")

    helper_enabled = bool(execution_context.get("privileged_helper_enabled")) if execution_context else False
    helper_effective = bool(execution_context.get("privileged_helper_effective")) if execution_context else False
    helper_hints = []
    cpu_power = telemetry.get("cpu_power_w") if isinstance(telemetry.get("cpu_power_w"), dict) else {}
    if helper_enabled and not helper_effective:
        helper_hints.append(
            "Privileged helper is enabled in settings, but sudo was not ready for non-interactive helper reads. "
            "Run Dependency Check from an interactive terminal and complete the sudo prompt, or verify sudo works for this user."
        )
    if not helper_effective and cpu_power.get("permission_issue"):
        helper_hints.append(
            "CPU package power is present but permission-limited; prepare the privileged helper "
            "to allow a narrow sudo RAPL read while keeping the suite itself as the normal user."
        )
    if not helper_effective and memory_identity and not memory_identity.get("available"):
        helper_hints.append(
            "DIMM manufacturer/part-number inventory may require the privileged helper for dmidecode "
            "on systems where inxi cannot read SMBIOS as a normal user."
        )
    if helper_hints:
        lines.append("")
        lines.append("Privileged Helper Suggestions:")
        for hint in helper_hints:
            lines.append(f"  - {hint}")

    gpu_matrix = ((telemetry.get("gpu_telemetry_by_gpu") or {}).get("gpus") or [])
    if isinstance(gpu_matrix, list) and gpu_matrix:
        lines.append("  - Per-GPU coverage:")
        for gpu in gpu_matrix[:8]:
            metrics = gpu.get("metrics") if isinstance(gpu.get("metrics"), dict) else {}
            available = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and detail.get("available")
            ]
            missing = [
                name
                for name, detail in metrics.items()
                if isinstance(detail, dict) and not detail.get("available")
            ]
            target = gpu.get("slot") or gpu.get("card") or f"gpu{gpu.get('gpu_index')}"
            lines.append(
                f"    GPU {gpu.get('gpu_index')} {target}: "
                + f"{len(available)} available, {len(missing)} missing"
            )
        if len(gpu_matrix) > 8:
            lines.append(f"    ... {len(gpu_matrix) - 8} more GPU(s)")

    drive_status = payload.get("google_drive_upload") if isinstance(payload.get("google_drive_upload"), dict) else {}
    if drive_status:
        missing = list(drive_status.get("missing") or [])
        lines.append("")
        lines.append("Upload / Sync:")
        lines.append(f"  - Google Drive upload: {'OK' if drive_status.get('ready') else 'not ready'}")
        lines.append(f"  - Credential path: {drive_status.get('credential_path')}")
        if missing:
            lines.append(f"  - Missing: {', '.join(str(item) for item in missing)}")

    lines.append("")
    return "\n".join(lines)
