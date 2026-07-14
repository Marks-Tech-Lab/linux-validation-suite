#!/usr/bin/env python3
"""OpenCL target matching, ICD, and fallback environment helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .lvs_gpu_identity import normalize_pci_id, normalize_pci_slot


def opencl_runtime_context_candidates(
    *,
    env_overrides: Optional[Dict[str, str]] = None,
    gpu_cards: Optional[List[Dict[str, Any]]] = None,
    native_probe: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = [{"context": "native", "env": {}}]
    current_rusticl = (dict(env_overrides or {}).get("RUSTICL_ENABLE") or "").strip()
    if current_rusticl:
        return candidates
    cards = list(gpu_cards or [])
    if not any(str(card.get("vendor", "")).strip().lower() == "amd" for card in cards):
        return candidates
    native_platforms = native_probe.get("platforms") if native_probe else []
    native_reason = str((native_probe or {}).get("reason", "") or "").lower()
    has_rusticl_platform = any(
        "rusticl" in str(platform_info.get("name", "")).lower()
        for platform_info in native_platforms or []
    )
    if has_rusticl_platform or "no opencl gpu devices found" in native_reason or "gpu devices unavailable" in native_reason:
        candidates.append(
            {
                "context": "rusticl_radeonsi",
                "env": {"RUSTICL_ENABLE": "radeonsi"},
            }
        )
    return candidates


def opencl_discover_icds(
    icd_dirs: Optional[List[Path]] = None,
) -> List[Dict[str, Any]]:
    paths = icd_dirs or [Path("/etc/OpenCL/vendors"), Path("/usr/share/OpenCL/vendors")]
    vendor_id_map = {"intel": "8086", "amd": "1002", "nvidia": "10de"}
    icds: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for icd_dir in paths:
        try:
            if not icd_dir.exists():
                continue
            for f in sorted(icd_dir.iterdir()):
                if f.suffix.lower() != ".icd":
                    continue
                resolved = str(f.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                stem = f.stem.lower()
                if any(kw in stem for kw in ("intel", "beignet", "neo")):
                    vendor_hint = "intel"
                elif any(kw in stem for kw in ("amd", "amdocl")):
                    vendor_hint = "amd"
                elif any(kw in stem for kw in ("nvidia", "cuda")):
                    vendor_hint = "nvidia"
                elif any(kw in stem for kw in ("rusticl", "mesa")):
                    vendor_hint = "rusticl"
                else:
                    vendor_hint = ""
                icds.append(
                    {
                        "label": f"icd:{f.stem}",
                        "path": str(f),
                        "vendor_hint": vendor_hint,
                        "vendor_id": normalize_pci_id(vendor_id_map.get(vendor_hint, "")),
                    }
                )
        except Exception:
            pass
    return icds


def opencl_find_icd(icds: List[Dict[str, Any]], keywords: Iterable[str]) -> Optional[Dict[str, Any]]:
    wanted = [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]
    if not wanted:
        return None
    for icd in icds:
        text = " ".join(
            [
                str(icd.get("label", "") or ""),
                str(icd.get("path", "") or ""),
                str(icd.get("vendor_hint", "") or ""),
            ]
        ).lower()
        if any(keyword in text for keyword in wanted):
            return dict(icd)
    return None


def opencl_env_candidates_for_target(
    target: Dict[str, Any],
    icds: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    vendor = str(target.get("vendor", "") or "").strip().lower()
    vendor_id = normalize_pci_id(str(target.get("vendor_id", "") or ""))
    candidates: List[Dict[str, Any]] = []

    def add(context: str, env: Dict[str, str]) -> None:
        key = (context, tuple(sorted((str(k), str(v)) for k, v in env.items())))
        if key in {
            (item["context"], tuple(sorted((str(k), str(v)) for k, v in item["env"].items())))
            for item in candidates
        }:
            return
        candidates.append({"context": context, "env": dict(env)})

    if vendor == "nvidia" or vendor_id == "10de":
        nvidia_icd = opencl_find_icd(icds, ["nvidia", "cuda"])
        if nvidia_icd:
            add("icd_nvidia", {"OCL_ICD_VENDORS": str(nvidia_icd["path"])})
        return candidates

    if vendor == "intel" or vendor_id == "8086":
        intel_icd = opencl_find_icd(icds, ["intel", "neo", "beignet"])
        rusticl_icd = opencl_find_icd(icds, ["rusticl", "mesa"])
        if intel_icd:
            add("icd_intel", {"OCL_ICD_VENDORS": str(intel_icd["path"])})
        if rusticl_icd:
            add(
                "rusticl_iris",
                {
                    "OCL_ICD_VENDORS": str(rusticl_icd["path"]),
                    "RUSTICL_ENABLE": "iris",
                },
            )
        return candidates

    if vendor == "amd" or vendor_id == "1002":
        amd_icd = opencl_find_icd(icds, ["amdocl", "amd"])
        rusticl_icd = opencl_find_icd(icds, ["rusticl", "mesa"])
        if amd_icd:
            add("icd_amd", {"OCL_ICD_VENDORS": str(amd_icd["path"])})
        if rusticl_icd:
            add(
                "rusticl_radeonsi",
                {
                    "OCL_ICD_VENDORS": str(rusticl_icd["path"]),
                    "RUSTICL_ENABLE": "radeonsi",
                },
            )
        else:
            add("rusticl_radeonsi", {"RUSTICL_ENABLE": "radeonsi"})
        return candidates

    return candidates


def opencl_device_identity_key(
    device: Dict[str, Any],
    required_env: Optional[Dict[str, str]] = None,
) -> Tuple[Any, ...]:
    return (
        normalize_pci_id(str(device.get("vendor_id", "") or "")),
        normalize_pci_slot(str(device.get("pci_slot", "") or "")).lower(),
        str(device.get("name", "") or "").strip().lower(),
        int(device.get("global_mem_bytes", 0) or 0),
        str(device.get("platform_name", "") or "").strip().lower(),
        tuple(sorted((str(k), str(v)) for k, v in (required_env or {}).items())),
    )


def append_opencl_probe_devices(
    devices: List[Dict[str, Any]],
    probe: Dict[str, Any],
    required_env: Dict[str, str],
    seen: Set[Tuple[Any, ...]],
) -> None:
    for device in probe.get("devices") or []:
        tagged = dict(
            device,
            required_env=dict(required_env),
            probe_context=str(probe.get("context", "") or ""),
        )
        identity = opencl_device_identity_key(tagged, required_env)
        if identity in seen:
            continue
        seen.add(identity)
        devices.append(tagged)


def gpu_vendor_aliases(vendor: Any) -> Set[str]:
    normalized = str(vendor or "").strip().lower()
    normalized_id = normalize_pci_id(normalized)
    if normalized in {"amd", "advanced micro devices"} or normalized_id == "1002":
        return {"amd", "advanced micro devices", "advanced micro devices, inc.", "ati", "radeon"}
    if normalized == "nvidia" or normalized_id == "10de":
        return {"nvidia", "nvidia corporation"}
    if normalized == "intel" or normalized_id == "8086":
        return {"intel", "intel(r)", "intel corporation", "intel(r) corporation"}
    return {normalized} if normalized else set()


def gpu_vendor_matches_text(vendor: Any, *texts: Any) -> bool:
    aliases = gpu_vendor_aliases(vendor)
    if not aliases:
        return False
    haystack = " ".join(str(text or "").strip().lower() for text in texts if str(text or "").strip())
    if not haystack:
        return False
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", haystack)
        if token
    }
    for alias in aliases:
        alias_text = str(alias or "").strip().lower()
        if not alias_text:
            continue
        alias_compact = re.sub(r"[^a-z0-9]+", "", alias_text)
        if len(alias_compact) <= 3:
            if alias_compact in tokens:
                return True
            continue
        if alias_text in haystack:
            return True
    return False
