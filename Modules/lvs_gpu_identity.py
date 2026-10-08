#!/usr/bin/env python3
"""GPU identity normalization helpers shared by frontends and backends."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def normalize_pci_id(value: Any) -> str:
    return str(value or "").strip().lower().removeprefix("0x")


def normalize_pci_slot(slot: Any) -> str:
    text = str(slot or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) == 3:
        domain = parts[0].lower().removeprefix("pci-")
        if len(domain) > 4:
            domain = domain[-4:]
        if len(domain) == 4:
            return f"{domain}:{parts[1]}:{parts[2]}"
    if len(parts) == 2:
        return f"0000:{text}"
    return text


def pci_physical_gpu_id(slot: Any) -> str:
    """Return the canonical physical identity for a PCI GPU, if available."""
    normalized = normalize_pci_slot(slot).lower()
    return f"pci:{normalized}" if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", normalized) else ""


def physical_gpu_identity(device: Dict[str, Any]) -> Dict[str, Any]:
    """Describe stable GPU identity without treating provider ordinals as identity."""
    slot = normalize_pci_slot(device.get("slot") or device.get("pci_slot") or device.get("pciSlot")).lower()
    provider_uuid = str(device.get("nvidia_uuid") or "").strip()
    pci_identity = pci_physical_gpu_id(slot)
    if pci_identity:
        aliases = [f"pci_bdf:{slot}"]
        card = str(device.get("card") or "").strip().lower()
        render_node = str(device.get("render_node") or device.get("drm_render_node") or "").strip()
        if card:
            aliases.append(f"drm_card:{card}")
        if render_node:
            aliases.append(f"drm_render_node:{render_node}")
        if provider_uuid:
            aliases.append(f"nvidia_uuid:{provider_uuid}")
        return {
            "physical_gpu_id": pci_identity,
            "identity_source": "pci_bdf",
            "identity_confidence": "high",
            "identity_aliases": aliases,
        }
    existing = str(device.get("physical_gpu_id") or "").strip()
    if existing:
        aliases = list(device.get("identity_aliases") or [])
        card = str(device.get("card") or "").strip().lower()
        render_node = str(device.get("render_node") or device.get("drm_render_node") or "").strip()
        if card and f"drm_card:{card}" not in aliases:
            aliases.append(f"drm_card:{card}")
        if render_node and f"drm_render_node:{render_node}" not in aliases:
            aliases.append(f"drm_render_node:{render_node}")
        return {
            "physical_gpu_id": existing,
            "identity_source": str(device.get("identity_source") or device.get("gpu_identity_source") or "existing"),
            "identity_confidence": str(device.get("identity_confidence") or "high"),
            "identity_aliases": aliases,
        }
    platform_path = str(device.get("platform_gpu_path") or device.get("platform_path") or "").strip()
    platform_name = str(device.get("platform_gpu_name") or device.get("platform_name") or "").strip()
    if platform_path or platform_name:
        stable_name = platform_name or platform_path.rstrip("/").rsplit("/", 1)[-1]
        return {
            "physical_gpu_id": f"platform:{stable_name}",
            "identity_source": "platform_device_tree",
            "identity_confidence": "high",
            "identity_aliases": [f"platform_path:{platform_path}"] if platform_path else [],
        }
    if provider_uuid:
        return {
            "physical_gpu_id": f"provider:nvidia:{provider_uuid}",
            "identity_source": "nvidia_uuid",
            "identity_confidence": "high",
            "identity_aliases": [f"nvidia_uuid:{provider_uuid}"],
        }
    return {
        "physical_gpu_id": "",
        "identity_source": "unresolved",
        "identity_confidence": "unresolved",
        "identity_aliases": [],
    }


def apply_physical_gpu_identity(device: Dict[str, Any]) -> Dict[str, Any]:
    identity = physical_gpu_identity(device)
    device.update(identity)
    # Retain the established source-map field while using one canonical source name.
    device["gpu_identity_source"] = identity["identity_source"]
    return device


def pci_slot_sort_key(slot: Any) -> Tuple[int, int, int, int]:
    normalized = normalize_pci_slot(slot)
    match = re.match(r"^([0-9a-fA-F]{4}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])$", normalized)
    if match is None:
        return (9999, 9999, 9999, 9999)
    return tuple(int(part, 16) for part in match.groups())


def gpu_vendor_name(vendor_id: Any) -> str:
    normalized = normalize_pci_id(vendor_id)
    mapping = {
        "1002": "AMD",
        "10de": "NVIDIA",
        "8086": "Intel",
    }
    return mapping.get(normalized, str(vendor_id or "").upper() or "Unknown")


def friendly_pci_gpu_name(vendor_name: Any, pci_name: Any, device_code: Any) -> str:
    name = str(pci_name or "").strip()
    vendor = str(vendor_name or "").strip()
    code = str(device_code or "").strip()
    generic_fallback = f"{vendor} GPU {code}".strip()
    if name and name.lower() == generic_fallback.lower():
        return name
    lower = name.lower()
    gpu_markers = (
        "radeon",
        "geforce",
        "rtx",
        "gtx",
        "quadro",
        "tesla",
        "arc",
        "uhd graphics",
        "iris",
        "graphics",
        "instinct",
    )
    if any(token in lower for token in gpu_markers):
        return name
    if vendor.lower() == "amd" and name:
        return f"AMD Radeon Graphics ({name})"
    if vendor.lower() == "intel" and name:
        return f"Intel Graphics ({name})"
    if vendor.lower() == "nvidia" and name:
        return f"NVIDIA GPU ({name})"
    return name or generic_fallback


def gpu_vendor_family_from_inventory(gpu: Dict[str, Any]) -> str:
    vendor_id = normalize_pci_id(gpu.get("vendor_id", ""))
    if vendor_id == "1002":
        return "amd"
    if vendor_id == "10de":
        return "nvidia"
    if vendor_id == "8086":
        return "intel"
    driver = str(gpu.get("driver", "") or "").strip().lower()
    if driver in {"amdgpu", "radeon"}:
        return "amd"
    if driver in {"nvidia", "nouveau"}:
        return "nvidia"
    if driver in {"i915", "xe"}:
        return "intel"
    return ""


def gpu_vendor_family_from_name(text: Any) -> str:
    lowered = str(text or "").lower()
    if re.search(r"\b(nvidia|geforce|rtx|gtx|quadro|tesla)\b", lowered):
        return "nvidia"
    if re.search(r"\b(intel|arc|uhd graphics|iris)\b", lowered):
        return "intel"
    if re.search(r"\b(amd|radeon|instinct)\b", lowered) or re.search(r"\brx\s*\d{3,5}\b", lowered):
        return "amd"
    return ""


def is_management_display_adapter(gpu: Dict[str, Any]) -> bool:
    driver = str(gpu.get("driver", "") or "").strip().lower()
    vendor_id = normalize_pci_id(gpu.get("vendor_id", ""))
    name_text = " ".join(
        str(gpu.get(key, "") or "")
        for key in ("name", "marketing_name", "pci_name", "chipset")
    ).lower()
    if driver in {"ast", "mgag200", "bochs-drm", "cirrus", "simpledrm"}:
        return True
    if vendor_id in {"1a03", "102b"} and not str(gpu.get("memory", "") or "").strip():
        return True
    if re.search(r"\b(aspeed|bmc|baseboard management|mgag200|matrox g200)\b", name_text):
        return True
    return False


def is_unhelpful_runtime_gpu_name(name: Any) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return True
    return any(token in text for token in ("llvmpipe", "softpipe", "swrast", "software rasterizer"))


def looks_like_cpu_package_gpu_name(name: Any) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    cpu_tokens = ("processor", "cpu", "ryzen", "xeon", "epyc", "threadripper", "athlon", "celeron", "pentium", "core(tm)")
    gpu_tokens = ("radeon", "geforce", "rtx", "gtx", "quadro", "tesla", "arc", "uhd graphics", "iris", "instinct")
    return any(token in text for token in cpu_tokens) and not any(token in text for token in gpu_tokens)


def clean_runtime_gpu_name(name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    text = re.sub(r"/PCIe/SSE2$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*\((?:radv|radeonsi|llvm|drm|mesa|navi|pci|sse2|gc_|gfx)[^)]*\)\s*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def runtime_gpu_name_score(gpu: Dict[str, Any], candidate: Dict[str, Any]) -> int:
    name = str(candidate.get("name") or "")
    raw = str(candidate.get("raw") or name)
    text = f"{name} {raw}".lower()
    if is_management_display_adapter(gpu):
        return -1000
    if is_unhelpful_runtime_gpu_name(raw) or looks_like_cpu_package_gpu_name(raw):
        return -1000
    target_vendor = gpu_vendor_family_from_inventory(gpu)
    candidate_vendor = gpu_vendor_family_from_name(text)
    if target_vendor and candidate_vendor and target_vendor != candidate_vendor:
        return -1000

    score = 0
    source = str(candidate.get("source") or "")
    if source == "egl_renderer":
        score += 80
    elif source == "vulkaninfo":
        score += 60

    gpu_tokens = (
        "radeon",
        "geforce",
        "rtx",
        "gtx",
        "quadro",
        "tesla",
        "arc",
        "uhd graphics",
        "iris",
        "graphics",
        "instinct",
        "pro ",
        "rx ",
    )
    if any(token in text for token in gpu_tokens):
        score += 120
    if re.search(r"\b(rx|rtx|gtx|a|l|w|pro)\s*\d{3,5}\b", text):
        score += 60
    if "processor" in text or re.search(r"\b(core|ryzen|xeon|epyc|threadripper|athlon|celeron|pentium)\b", text):
        score -= 250
    if "/" in name or "[" in name or "]" in name:
        score -= 20

    pci_name = str(gpu.get("pci_name") or gpu.get("name") or "").lower()
    if pci_name and name.lower() == pci_name:
        score -= 30
    return score


def select_runtime_gpu_name(gpu: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [
        (runtime_gpu_name_score(gpu, candidate), candidate)
        for candidate in candidates
        if candidate.get("name")
    ]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return {}
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def parse_vulkan_summary_devices(text: Any) -> List[Dict[str, str]]:
    devices: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if re.match(r"\s*GPU\d+:", line):
            if current:
                devices.append(current)
            current = {}
            continue
        if not current and not devices and not re.match(r"\s*[A-Za-z0-9_]+\s*=", line):
            continue
        match = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(.+)", line)
        if match is not None:
            current[match.group(1).strip()] = match.group(2).strip()
    if current:
        devices.append(current)
    return devices


def device_class_from_vulkan_type(device_type: Any) -> str:
    text = str(device_type or "").strip().lower()
    if "discrete" in text:
        return "discrete"
    if "integrated" in text:
        return "integrated"
    if "virtual" in text:
        return "virtual"
    if re.search(r"\bcpu\b", text):
        return "cpu"
    return "unknown"


def slot_from_mesa_vulkan_uuid(uuid_text: Any, drm_gpus: List[Dict[str, Any]]) -> str:
    match = re.match(r"^00000000-([0-9a-fA-F]{2})00-", str(uuid_text or ""))
    if match is None:
        return ""
    bus = match.group(1).lower()
    candidates = [
        str(gpu.get("pci_slot", ""))
        for gpu in drm_gpus
        if len(str(gpu.get("pci_slot", "")).split(":")) >= 2
        and str(gpu.get("pci_slot", "")).split(":")[1].lower() == bus
    ]
    return candidates[0] if len(candidates) == 1 else ""


def slot_for_vulkan_device(device: Dict[str, Any], drm_gpus: List[Dict[str, Any]]) -> str:
    vendor = normalize_pci_id(device.get("vendorID", ""))
    device_id = normalize_pci_id(device.get("deviceID", ""))
    uuid_slot = slot_from_mesa_vulkan_uuid(str(device.get("deviceUUID", "") or ""), drm_gpus)
    if uuid_slot:
        for gpu in drm_gpus:
            if (
                str(gpu.get("pci_slot", "")).lower() == uuid_slot.lower()
                and normalize_pci_id(gpu.get("vendor_id", "")) == vendor
                and normalize_pci_id(gpu.get("device_id", "")) == device_id
            ):
                return str(gpu.get("pci_slot", ""))
        return uuid_slot
    matches = [
        str(gpu.get("pci_slot", ""))
        for gpu in drm_gpus
        if normalize_pci_id(gpu.get("vendor_id", "")) == vendor
        and normalize_pci_id(gpu.get("device_id", "")) == device_id
    ]
    return matches[0] if len(matches) == 1 else ""
