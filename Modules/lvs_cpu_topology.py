#!/usr/bin/env python3
"""CPU topology summary helpers for system inventory/export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


ReadText = Callable[[Path], Optional[str]]


# Linux arm64 cputype.h implementer/part identifiers. Keep this deliberately
# bounded to architecturally identified cores; unknown values remain visible in
# persisted evidence instead of being guessed from frequency or CPU ordering.
ARM_IMPLEMENTER_NAMES = {
    0x41: "Arm",
    0x43: "Cavium",
    0x46: "Fujitsu",
    0x4E: "NVIDIA",
    0x51: "Qualcomm",
    0x61: "Apple",
    0xC0: "Ampere",
}

ARM_CORE_MODELS = {
    (0x41, 0xD03): "ARM Cortex-A53",
    (0x41, 0xD04): "ARM Cortex-A35",
    (0x41, 0xD05): "ARM Cortex-A55",
    (0x41, 0xD07): "ARM Cortex-A57",
    (0x41, 0xD08): "ARM Cortex-A72",
    (0x41, 0xD09): "ARM Cortex-A73",
    (0x41, 0xD0A): "ARM Cortex-A75",
    (0x41, 0xD0B): "ARM Cortex-A76",
    (0x41, 0xD0C): "ARM Neoverse-N1",
    (0x41, 0xD0D): "ARM Cortex-A77",
    (0x41, 0xD0E): "ARM Cortex-A76AE",
    (0x41, 0xD40): "ARM Neoverse-V1",
    (0x41, 0xD41): "ARM Cortex-A78",
    (0x41, 0xD42): "ARM Cortex-A78AE",
    (0x41, 0xD44): "ARM Cortex-X1",
    (0x41, 0xD46): "ARM Cortex-A510",
    (0x41, 0xD47): "ARM Cortex-A710",
    (0x41, 0xD48): "ARM Cortex-X2",
    (0x41, 0xD49): "ARM Neoverse-N2",
    (0x41, 0xD4B): "ARM Cortex-A78C",
    (0x41, 0xD4C): "ARM Cortex-X1C",
    (0x41, 0xD4D): "ARM Cortex-A715",
    (0x41, 0xD4E): "ARM Cortex-X3",
    (0x41, 0xD4F): "ARM Neoverse-V2",
    (0x41, 0xD80): "ARM Cortex-A520",
    (0x41, 0xD81): "ARM Cortex-A720",
    (0x41, 0xD82): "ARM Cortex-X4",
    (0x41, 0xD83): "ARM Neoverse-V3AE",
    (0x41, 0xD84): "ARM Neoverse-V3",
    (0x41, 0xD85): "ARM Cortex-X925",
    (0x41, 0xD87): "ARM Cortex-A725",
    (0x41, 0xD89): "ARM Cortex-A720AE",
    (0x41, 0xD8E): "ARM Neoverse-N3",
    (0x51, 0x001): "Qualcomm Oryon",
    (0x51, 0x200): "Qualcomm Kryo",
    (0x51, 0x801): "Qualcomm Kryo 2xx Silver",
    (0x51, 0x802): "Qualcomm Kryo 3xx Gold",
    (0x51, 0x803): "Qualcomm Kryo 3xx Silver",
    (0x51, 0x804): "Qualcomm Kryo 4xx Gold",
    (0x51, 0x805): "Qualcomm Kryo 4xx Silver",
    (0x51, 0xC00): "Qualcomm Falkor",
    (0x4E, 0x003): "NVIDIA Denver",
    (0x4E, 0x004): "NVIDIA Carmel",
    (0x46, 0x001): "Fujitsu A64FX",
    (0xC0, 0xAC3): "Ampere-1",
    (0xC0, 0xAC4): "Ampere-1A",
}


def _hex(value: int, width: int) -> str:
    return f"0x{int(value):0{width}x}"


def decode_arm_midr(value: Any) -> Dict[str, Any]:
    """Decode one MIDR_EL1 value while preserving unknown identifiers."""
    try:
        midr = int(str(value).strip(), 0) if not isinstance(value, int) else value
    except (TypeError, ValueError):
        return {
            "Status": "unknown",
            "Reason": "invalid_midr",
            "RawMidr": str(value or ""),
        }
    if midr < 0 or midr > 0xFFFFFFFFFFFFFFFF:
        return {"Status": "unknown", "Reason": "invalid_midr", "RawMidr": str(value)}
    implementer = (midr >> 24) & 0xFF
    variant = (midr >> 20) & 0xF
    architecture = (midr >> 16) & 0xF
    part = (midr >> 4) & 0xFFF
    revision = midr & 0xF
    model = ARM_CORE_MODELS.get((implementer, part), "")
    return {
        "Status": "identified" if model else "unknown_model",
        "Reason": "" if model else "unmapped_implementer_part",
        "Model": model or "Unknown ARM core",
        "RawMidr": _hex(midr, 16),
        "Implementer": _hex(implementer, 2),
        "ImplementerName": ARM_IMPLEMENTER_NAMES.get(implementer, "Unknown implementer"),
        "Architecture": _hex(architecture, 1),
        "Variant": _hex(variant, 1),
        "Part": _hex(part, 3),
        "Revision": revision,
    }


def parse_proc_cpuinfo_identities(cpuinfo_text: str) -> Dict[int, Dict[str, Any]]:
    """Parse per-processor model and ARM identity fields from /proc/cpuinfo."""
    records: Dict[int, Dict[str, str]] = {}
    current: Dict[str, str] = {}

    def finish() -> None:
        raw_index = current.get("processor", "")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        records[index] = dict(current)

    for raw_line in str(cpuinfo_text or "").splitlines() + [""]:
        line = raw_line.strip()
        if not line:
            if current:
                finish()
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        current[key.lower()] = value

    identities: Dict[int, Dict[str, Any]] = {}
    for index, fields in records.items():
        identity: Dict[str, Any] = {
            "CpuId": index,
            "Source": "proc_cpuinfo",
            "Confidence": "high",
        }
        model_name = fields.get("model name", "")
        numeric: Dict[str, int] = {}
        for field, output in (
            ("cpu implementer", "Implementer"),
            ("cpu architecture", "Architecture"),
            ("cpu variant", "Variant"),
            ("cpu part", "Part"),
            ("cpu revision", "Revision"),
        ):
            if field not in fields:
                continue
            try:
                numeric[output] = int(fields[field], 0)
            except (TypeError, ValueError):
                identity.setdefault("InvalidFields", {})[output] = fields[field]
        for output, value in numeric.items():
            if output == "Implementer":
                identity[output] = _hex(value, 2)
                identity["ImplementerName"] = ARM_IMPLEMENTER_NAMES.get(value, "Unknown implementer")
            elif output == "Part":
                identity[output] = _hex(value, 3)
            elif output in {"Architecture", "Variant"}:
                identity[output] = _hex(value, 1)
            else:
                identity[output] = value
        if "Implementer" in numeric and "Part" in numeric:
            implementer = numeric["Implementer"]
            part = numeric["Part"]
            model = ARM_CORE_MODELS.get((implementer, part), "")
            identity.update({
                "Status": "identified" if model else "unknown_model",
                "Reason": "" if model else "unmapped_implementer_part",
                "Model": model or "Unknown ARM core",
                "Implementer": _hex(implementer, 2),
                "ImplementerName": ARM_IMPLEMENTER_NAMES.get(implementer, "Unknown implementer"),
                "Part": _hex(part, 3),
            })
        elif model_name:
            identity.update({
                "Status": "described",
                "Reason": "model_name_without_architectural_ids",
                "Model": model_name,
                "Confidence": "descriptive",
            })
        else:
            identity.update({
                "Status": "unknown",
                "Reason": (
                    "partial_architectural_identity"
                    if numeric or identity.get("InvalidFields")
                    else "architectural_identity_fields_missing"
                ),
                "Model": "Unknown CPU core",
                "Confidence": "none",
            })
        identities[index] = identity
    return identities


def discover_cpu_architectural_identities(
    cpu_root: Path,
    cpuinfo_text: str,
    read_text: ReadText,
) -> Dict[int, Dict[str, Any]]:
    """Resolve per-CPU identity, preferring stable sysfs MIDR evidence."""
    proc_identities = parse_proc_cpuinfo_identities(cpuinfo_text)
    cpu_ids = {
        _cpu_index_from_path(path)
        for path in cpu_root.glob("cpu[0-9]*")
        if path.is_dir() and _cpu_index_from_path(path) >= 0
    } | set(proc_identities)
    identities: Dict[int, Dict[str, Any]] = {}
    for cpu_id in sorted(cpu_ids):
        midr_path = cpu_root / f"cpu{cpu_id}" / "regs" / "identification" / "midr_el1"
        raw_midr = read_text(midr_path)
        if raw_midr not in (None, ""):
            decoded = decode_arm_midr(raw_midr)
            if decoded.get("Reason") != "invalid_midr":
                decoded.update({
                    "CpuId": cpu_id,
                    "Source": "sysfs_midr_el1",
                    "SourcePath": str(midr_path),
                    "Confidence": "authoritative",
                })
                identities[cpu_id] = decoded
                continue
        fallback = dict(proc_identities.get(cpu_id, {}))
        if fallback:
            fallback["FallbackReason"] = (
                "sysfs_midr_invalid"
                if raw_midr not in (None, "")
                else ("sysfs_midr_unreadable" if midr_path.exists() else "sysfs_midr_unavailable")
            )
            identities[cpu_id] = fallback
            continue
        identities[cpu_id] = {
            "CpuId": cpu_id,
            "Status": "unknown",
            "Model": "Unknown CPU core",
            "Source": "none",
            "Confidence": "none",
            "Reason": (
                "sysfs_midr_unreadable_and_proc_cpuinfo_identity_unavailable"
                if midr_path.exists()
                else "midr_and_proc_cpuinfo_identity_unavailable"
            ),
            "SourcePath": str(midr_path),
        }
    return identities


def parse_lscpu_cpu_identity(lscpu_text: str) -> str:
    """Return a useful vendor/model identity when /proc/cpuinfo lacks model name."""
    fields: Dict[str, str] = {}
    for raw_line in str(lscpu_text or "").splitlines():
        if ":" not in raw_line:
            continue
        key, value = [part.strip() for part in raw_line.split(":", 1)]
        fields[key.lower()] = value
    model = fields.get("model name", "")
    vendor = fields.get("vendor id", "")
    if not model:
        return ""
    if vendor and vendor.lower() not in model.lower():
        return f"{vendor} {model}"
    return model


def parse_proc_cpuinfo_models(cpuinfo_text: str) -> Dict[int, str]:
    """Return processor index -> model name from /proc/cpuinfo text."""
    return {
        cpu_id: str(identity.get("Model") or "")
        for cpu_id, identity in parse_proc_cpuinfo_identities(cpuinfo_text).items()
        if identity.get("Status") == "described" and identity.get("Model")
    }


def _cpu_index_from_path(path: Path) -> int:
    try:
        return int(path.name.replace("cpu", ""))
    except Exception:
        return -1


def _safe_int(text: Optional[str]) -> Optional[int]:
    try:
        return int(str(text or "").strip(), 0)
    except Exception:
        return None


def _compact_cpu_list(values: Iterable[int]) -> str:
    ordered = sorted({int(value) for value in values})
    if not ordered:
        return ""
    ranges: List[str] = []
    start = prev = ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def classify_cpu_performance_classes(
    records: Dict[str, Dict[str, Any]],
) -> tuple[Dict[str, str], Dict[str, str], Dict[str, Optional[int]]]:
    """Classify neutral performance tiers without asserting core identity."""
    for field, source in (
        ("CpuCapacity", "cpu_capacity"),
        ("CppcHighestPerf", "acpi_cppc_highest_perf"),
        ("CpuinfoMaxFreqKHz", "cpuinfo_max_freq"),
        ("BaseFrequencyKHz", "base_frequency"),
    ):
        values = {
            key: int(record[field])
            for key, record in records.items()
            if isinstance(record.get(field), int) and int(record[field]) > 0
        }
        if len(values) < 2 or len(set(values.values())) < 2:
            continue
        tiers: List[tuple[float, List[str]]] = []
        for key, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
            for tier_index, (tier_value, tier_keys) in enumerate(tiers):
                if tier_value > 0 and abs(float(value) - tier_value) / tier_value <= 0.03:
                    tier_keys.append(key)
                    tiers[tier_index] = (
                        sum(values[tier_key] for tier_key in tier_keys) / len(tier_keys),
                        tier_keys,
                    )
                    break
            else:
                tiers.append((float(value), [key]))
        if len(tiers) < 2 or len(tiers) > 3 or tiers[-1][0] / tiers[0][0] >= 0.85:
            continue
        classes: Dict[str, str] = {}
        for tier_index, (_tier_value, tier_keys) in enumerate(tiers):
            tier_class = (
                "higher_capacity"
                if tier_index == 0
                else ("lower_capacity" if tier_index == len(tiers) - 1 else "intermediate_capacity")
            )
            for key in tier_keys:
                classes[key] = tier_class
        for key in records:
            classes.setdefault(key, "unknown")
        return (
            classes,
            {key: source if key in values else "unavailable" for key in records},
            {key: values.get(key) for key in records},
        )
    return (
        {key: "unknown" for key in records},
        {key: "unavailable" for key in records},
        {key: None for key in records},
    )


def _model_summary(model_counts: Dict[str, int], unknown_count: int) -> str:
    parts = [f"{count}x {model}" for model, count in sorted(model_counts.items())]
    if unknown_count:
        parts.append(f"{unknown_count}x Unknown ARM core")
    return " + ".join(parts)


def _performance_summary(class_counts: Dict[str, int], physical_count: int) -> str:
    useful = [
        (name, count)
        for name, count in (
            ("higher-capacity", class_counts.get("higher_capacity", 0)),
            ("intermediate-capacity", class_counts.get("intermediate_capacity", 0)),
            ("lower-capacity", class_counts.get("lower_capacity", 0)),
        )
        if count
    ]
    if len(useful) < 2:
        return ""
    return f"{physical_count}-core heterogeneous ARM CPU (" + ", ".join(
        f"{count} {name}" for name, count in useful
    ) + ")"


def _summary_name(package_records: List[Dict[str, Any]], fallback_name: str) -> str:
    names = [str(record.get("Name") or "").strip() for record in package_records]
    names = [name for name in names if name]
    if not names:
        return fallback_name
    unique_names = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)
    if len(names) > 1 and len(unique_names) == 1:
        return f"{len(names)}x {unique_names[0]}"
    if len(names) > 1:
        return " | ".join(
            f"CPU{index}: {name or fallback_name or 'Unknown CPU'}"
            for index, name in enumerate(names)
        )
    return names[0]


def _cpu_package_device(record: Dict[str, Any]) -> Dict[str, Any]:
    package_id = record.get("PackageId")
    name = str(record.get("Name") or "Unknown CPU")
    return {
        "DeviceId": f"cpu_package_{package_id}",
        "PackageId": package_id,
        "Name": name,
        "DisplayName": f"CPU {package_id}: {name}",
        "LogicalCpuCount": record.get("LogicalCpuCount", 0),
        "LogicalCpuRange": record.get("LogicalCpuRange", ""),
        "PhysicalCoreCount": record.get("PhysicalCoreCount", 0),
    }


def cpu_package_devices_from_topology(topology: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return additive per-package CPU device records from a topology block."""
    packages = topology.get("Packages") if isinstance(topology, dict) else []
    if not isinstance(packages, list):
        return []
    return [_cpu_package_device(record) for record in packages if isinstance(record, dict)]


def collect_cpu_topology_info(
    *,
    cpu_root: Path = Path("/sys/devices/system/cpu"),
    cpuinfo_text: str = "",
    read_text: Optional[ReadText] = None,
    fallback_name: str = "",
    core_type_probe: Optional[Dict[str, Any]] = None,
    architecture: str = "",
) -> Dict[str, Any]:
    """Build a socket/package-aware topology summary from Linux sysfs."""
    reader = read_text or (lambda path: path.read_text(encoding="utf-8", errors="ignore").strip())
    cpu_models = parse_proc_cpuinfo_models(cpuinfo_text)
    identities = discover_cpu_architectural_identities(cpu_root, cpuinfo_text, reader)
    architecture_lower = str(architecture or "").lower()
    arm_architecture = architecture_lower in {"arm64", "aarch64", "arm", "armv8", "armv8l"} or any(
        identity.get("Implementer") for identity in identities.values()
    )
    cpu_dirs = sorted(
        [path for path in cpu_root.glob("cpu[0-9]*") if path.is_dir()],
        key=_cpu_index_from_path,
    )
    packages: Dict[int, Dict[str, Any]] = {}
    all_physical_keys: set[str] = set()
    logical_count = 0
    probe_by_cpu = {
        int(item.get("cpu_id")): dict(item)
        for item in list((core_type_probe or {}).get("logical_cpus") or [])
        if isinstance(item, dict) and item.get("cpu_id") is not None
    }

    for cpu_dir in cpu_dirs:
        cpu_index = _cpu_index_from_path(cpu_dir)
        if cpu_index < 0:
            continue
        topology_dir = cpu_dir / "topology"
        package_id = _safe_int(reader(topology_dir / "physical_package_id"))
        core_id = _safe_int(reader(topology_dir / "core_id"))
        cluster_id = _safe_int(reader(topology_dir / "cluster_id"))
        thread_siblings = str(reader(topology_dir / "thread_siblings_list") or "").strip()
        if package_id is None:
            package_id = 0
        logical_count += 1
        identity = dict(identities.get(cpu_index, {}))
        identified_model = (
            str(identity.get("Model") or "")
            if identity.get("Status") == "identified"
            else ""
        )
        model_name = identified_model or cpu_models.get(cpu_index) or fallback_name or "Unknown CPU"
        record = packages.setdefault(
            package_id,
            {
                "PackageId": package_id,
                "Name": model_name,
                "LogicalCpuIndexes": [],
                "LogicalCpus": [],
                "PhysicalCoreKeys": set(),
            },
        )
        if not record.get("Name") or record.get("Name") == "Unknown CPU":
            record["Name"] = model_name
        record["LogicalCpuIndexes"].append(cpu_index)
        if core_id is not None and cluster_id is not None:
            physical_key = f"package{package_id}:cluster{cluster_id}:core{core_id}"
        elif core_id is not None:
            physical_key = f"package{package_id}:core{core_id}"
        elif thread_siblings:
            physical_key = f"package{package_id}:threads{thread_siblings}"
        else:
            physical_key = f"package{package_id}:cpu{cpu_index}"
        performance_record = {
            "CpuCapacity": _safe_int(reader(cpu_dir / "cpu_capacity")),
            "CppcHighestPerf": _safe_int(reader(cpu_dir / "acpi_cppc" / "highest_perf")),
            "CpuinfoMaxFreqKHz": _safe_int(reader(cpu_dir / "cpufreq" / "cpuinfo_max_freq")),
            "BaseFrequencyKHz": _safe_int(reader(cpu_dir / "cpufreq" / "base_frequency")),
        }
        probe = probe_by_cpu.get(cpu_index, {})
        interpreted = str(probe.get("interpreted_core_type") or "")
        pin_valid = (
            bool(probe.get("affinity_applied"))
            and int(probe.get("cpu_id", -1)) == cpu_index
            and int(probe.get("observed_cpu", -2)) == cpu_index
        )
        if not pin_valid:
            interpreted = ""
        if interpreted not in {"P", "E"}:
            interpreted = "P" if pin_valid and str(probe.get("vendor") or "") == "GenuineIntel" and not bool(probe.get("hybrid_flag")) else "U"
        classification_source = (
            "intel_cpuid_1a_pinned"
            if interpreted in {"P", "E"} and bool(probe.get("hybrid_flag"))
            else ("intel_cpuid_non_hybrid" if interpreted == "P" and probe else "unclassified")
        )
        record["LogicalCpus"].append(
            {
                "CpuId": cpu_index,
                "PackageId": package_id,
                "ClusterId": cluster_id,
                "CoreId": core_id,
                "ThreadSiblings": thread_siblings,
                "CoreType": interpreted,
                "CoreClass": "E-Core" if interpreted == "E" else ("P-Core" if interpreted == "P" else "Unknown Core Type"),
                "CoreTypeClassificationSource": classification_source,
                "CoreTypeEvidence": probe,
                "CoreModel": identified_model or ("Unknown ARM core" if arm_architecture else ""),
                "CoreIdentity": identity,
                "CoreIdentityStatus": identity.get("Status", "unknown"),
                "CoreIdentitySource": identity.get("Source", "none"),
                "CoreIdentityConfidence": identity.get("Confidence", "none"),
                "PhysicalCoreKey": physical_key,
                **performance_record,
            }
        )
        record["PhysicalCoreKeys"].add(physical_key)
        all_physical_keys.add(physical_key)

    physical_performance_records: Dict[str, Dict[str, Any]] = {}
    for record in packages.values():
        for logical_cpu in record.get("LogicalCpus", []):
            key = str(logical_cpu.get("PhysicalCoreKey") or "")
            if key and key not in physical_performance_records:
                physical_performance_records[key] = logical_cpu
    performance_by_physical, performance_source_by_physical, performance_value_by_physical = (
        classify_cpu_performance_classes(physical_performance_records)
    )
    for record in packages.values():
        for logical_cpu in record.get("LogicalCpus", []):
            key = str(logical_cpu.get("PhysicalCoreKey") or "")
            logical_cpu["PerformanceClass"] = performance_by_physical.get(key, "unknown")
            logical_cpu["PerformanceClassSource"] = performance_source_by_physical.get(key, "unavailable")
            logical_cpu["PerformanceClassValue"] = performance_value_by_physical.get(key)

    package_records: List[Dict[str, Any]] = []
    all_physical_types: Dict[str, str] = {}
    all_physical_identities: Dict[str, str] = {}
    all_physical_performance: Dict[str, str] = {}
    for package_id in sorted(packages):
        record = packages[package_id]
        logical_indexes = sorted(record.get("LogicalCpuIndexes", []))
        physical_keys = sorted(record.get("PhysicalCoreKeys", []))
        logical_cpus = sorted(record.get("LogicalCpus", []), key=lambda item: int(item["CpuId"]))
        clusters: Dict[str, Dict[str, Any]] = {}
        for logical_cpu in logical_cpus:
            cluster_id = logical_cpu.get("ClusterId")
            cluster_key = str(cluster_id) if cluster_id is not None else "unspecified"
            cluster = clusters.setdefault(
                cluster_key,
                {"ClusterId": cluster_id, "LogicalCpuIndexes": [], "PhysicalCoreKeys": set()},
            )
            cluster["LogicalCpuIndexes"].append(int(logical_cpu["CpuId"]))
            core_id = logical_cpu.get("CoreId")
            if core_id is not None:
                physical_key = f"package{package_id}:cluster{cluster_key}:core{core_id}"
            else:
                physical_key = f"package{package_id}:cluster{cluster_key}:cpu{logical_cpu['CpuId']}"
            cluster["PhysicalCoreKeys"].add(physical_key)
            current_type = str(logical_cpu.get("CoreType") or "U")
            prior_type = all_physical_types.get(physical_key)
            all_physical_types[physical_key] = current_type if prior_type in (None, current_type) else "U"
            identity_model = (
                str(logical_cpu.get("CoreModel") or "")
                if logical_cpu.get("CoreIdentityStatus") == "identified"
                else ""
            )
            prior_model = all_physical_identities.get(physical_key)
            all_physical_identities[physical_key] = (
                identity_model if prior_model in (None, identity_model) else ""
            )
            performance_class = str(logical_cpu.get("PerformanceClass") or "unknown")
            prior_performance = all_physical_performance.get(physical_key)
            all_physical_performance[physical_key] = (
                performance_class
                if prior_performance in (None, performance_class)
                else "unknown"
            )
        cluster_records = [
            {
                "ClusterId": item["ClusterId"],
                "LogicalCpuCount": len(item["LogicalCpuIndexes"]),
                "LogicalCpuRange": _compact_cpu_list(item["LogicalCpuIndexes"]),
                "PhysicalCoreCount": len(item["PhysicalCoreKeys"]),
            }
            for _, item in sorted(
                clusters.items(),
                key=lambda entry: (
                    entry[1]["ClusterId"] is None,
                    int(entry[1]["ClusterId"]) if entry[1]["ClusterId"] is not None else 0,
                ),
            )
        ]
        package_model_counts: Dict[str, int] = {}
        package_unknown = 0
        for key in physical_keys:
            model = all_physical_identities.get(key, "")
            if model:
                package_model_counts[model] = package_model_counts.get(model, 0) + 1
            else:
                package_unknown += 1
        package_performance_counts: Dict[str, int] = {}
        for key in physical_keys:
            performance_class = all_physical_performance.get(key, "unknown")
            package_performance_counts[performance_class] = package_performance_counts.get(performance_class, 0) + 1
        package_name = (
            _model_summary(package_model_counts, package_unknown)
            if package_model_counts and (len(package_model_counts) > 1 or package_unknown)
            else (
                next(iter(package_model_counts))
                if package_model_counts
                else (
                    _performance_summary(package_performance_counts, len(physical_keys))
                    if arm_architecture
                    else ""
                ) or str(record.get("Name") or fallback_name or "Unknown CPU")
            )
        )
        package_records.append(
            {
                "PackageId": package_id,
                "Name": package_name,
                "LogicalCpuCount": len(logical_indexes),
                "LogicalCpuRange": _compact_cpu_list(logical_indexes),
                "PhysicalCoreCount": len(physical_keys),
                "Clusters": cluster_records,
                "LogicalCpus": logical_cpus,
            }
        )

    name_summary = _summary_name(package_records, fallback_name or "Unknown CPU")
    model_counts: Dict[str, int] = {}
    unknown_identity_count = 0
    for key in all_physical_keys:
        model = all_physical_identities.get(key, "")
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1
        else:
            unknown_identity_count += 1
    performance_counts: Dict[str, int] = {}
    for value in all_physical_performance.values():
        performance_counts[value] = performance_counts.get(value, 0) + 1
    if model_counts and (len(model_counts) > 1 or unknown_identity_count):
        name_summary = _model_summary(model_counts, unknown_identity_count)
    elif len(model_counts) == 1 and unknown_identity_count == 0:
        name_summary = next(iter(model_counts))
    elif arm_architecture:
        name_summary = _performance_summary(performance_counts, len(all_physical_keys)) or fallback_name or "Unknown ARM CPU"
    package_devices = [_cpu_package_device(record) for record in package_records]
    package_names = [str(record.get("Name") or "Unknown CPU") for record in package_records]
    package_count = len(package_records) if package_records else (1 if fallback_name else 0)
    aggregate = {
        "Name": name_summary,
        "BaseName": fallback_name or name_summary or "Unknown CPU",
        "PackageCount": package_count,
        "LogicalCpuCount": logical_count,
        "PhysicalCoreCount": len(all_physical_keys),
        "PCoreCount": sum(1 for value in all_physical_types.values() if value == "P"),
        "ECoreCount": sum(1 for value in all_physical_types.values() if value == "E"),
        "UnknownCoreTypeCount": sum(1 for value in all_physical_types.values() if value not in {"P", "E"}),
        "CoreModelCounts": [
            {"Model": model, "PhysicalCoreCount": count}
            for model, count in sorted(model_counts.items())
        ],
        "UnknownCoreIdentityCount": unknown_identity_count,
        "CoreIdentityComplete": bool(all_physical_keys) and unknown_identity_count == 0,
        "PerformanceClassCounts": dict(sorted(performance_counts.items())),
    }
    return {
        "NameSummary": name_summary,
        "Aggregate": aggregate,
        "PackageCount": package_count,
        "LogicalCpuCount": logical_count,
        "PhysicalCoreCount": len(all_physical_keys),
        "Packages": package_records,
        "PackageNames": package_names,
        "PackageDevices": package_devices,
        "CoreTypeProbe": dict(core_type_probe or {}),
        "CoreTypeSummary": {
            "PhysicalPCoreCount": aggregate["PCoreCount"],
            "PhysicalECoreCount": aggregate["ECoreCount"],
            "PhysicalUnknownCoreTypeCount": aggregate["UnknownCoreTypeCount"],
        },
        "CoreIdentitySummary": {
            "Models": aggregate["CoreModelCounts"],
            "PhysicalIdentifiedCoreCount": len(all_physical_keys) - unknown_identity_count,
            "PhysicalUnknownCoreCount": unknown_identity_count,
            "Complete": aggregate["CoreIdentityComplete"],
        },
        "PerformanceClassSummary": {
            "PhysicalCoreCount": len(all_physical_keys),
            "Classes": aggregate["PerformanceClassCounts"],
        },
        "ArchitectureFamily": "arm" if arm_architecture else "other",
    }
