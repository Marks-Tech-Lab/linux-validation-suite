from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


WorkerErrorCountFn = Callable[[List[Dict[str, Any]]], int]


class GpuTargetingResolver:
    """Resolve parsed GPU identity, order, class, and target/observer state."""

    def __init__(self, *, worker_integrity_error_count: WorkerErrorCountFn) -> None:
        self._worker_integrity_error_count = worker_integrity_error_count

    def name_map(
        self,
        gpu_inventory: List[Dict[str, Any]],
        telemetry: Optional[Any] = None,
    ) -> Dict[int, str]:
        names_by_index = {
            index: gpu.get("Name") or gpu.get("GpuModel") or f"GPU {index}"
            for index, gpu in enumerate(gpu_inventory)
        }
        by_slot = {
            self.normalize_interface(gpu.get("Interface")): gpu.get("Name") or gpu.get("GpuModel") or ""
            for gpu in gpu_inventory
            if self.normalize_interface(gpu.get("Interface"))
        }
        by_card = {
            str(gpu.get("Card") or "").strip().lower(): gpu.get("Name") or gpu.get("GpuModel") or ""
            for gpu in gpu_inventory
            if str(gpu.get("Card") or "").strip()
        }
        if telemetry is not None:
            for source in getattr(telemetry, "_gpu_sources", []):
                try:
                    gpu_index = int(source.get("gpu_index", 0))
                except Exception:
                    continue
                slot = self.normalize_interface(source.get("slot"))
                card = str(source.get("card") or "").strip().lower()
                if not card:
                    label = str(source.get("label") or "")
                    match = re.search(r"\b(card[0-9]+)\b", label)
                    if match is not None:
                        card = match.group(1).lower()
                name = by_slot.get(slot) or by_card.get(card) or ""
                if name:
                    names_by_index[gpu_index] = name
        return names_by_index

    def order_map(
        self,
        gpu_inventory: List[Dict[str, Any]],
        telemetry: Optional[Any] = None,
    ) -> Dict[int, int]:
        order_by_index = {index: index for index, _ in enumerate(gpu_inventory)}
        by_slot = {
            self.normalize_interface(gpu.get("Interface")): index
            for index, gpu in enumerate(gpu_inventory)
            if self.normalize_interface(gpu.get("Interface"))
        }
        by_card = {
            str(gpu.get("Card") or "").strip().lower(): index
            for index, gpu in enumerate(gpu_inventory)
            if str(gpu.get("Card") or "").strip()
        }
        if telemetry is not None:
            for source in getattr(telemetry, "_gpu_sources", []):
                try:
                    gpu_index = int(source.get("gpu_index", 0))
                except Exception:
                    continue
                slot = self.normalize_interface(source.get("slot"))
                card = str(source.get("card") or "").strip().lower()
                if not card:
                    label = str(source.get("label") or "")
                    match = re.search(r"\b(card[0-9]+)\b", label)
                    if match is not None:
                        card = match.group(1).lower()
                if slot in by_slot:
                    order_by_index[gpu_index] = by_slot[slot]
                elif card in by_card:
                    order_by_index[gpu_index] = by_card[card]
        return order_by_index

    def device_class_map(
        self,
        gpu_inventory: List[Dict[str, Any]],
        telemetry: Optional[Any] = None,
    ) -> Dict[int, str]:
        classes_by_index = {
            index: str(gpu.get("DeviceClass") or "").strip().lower()
            for index, gpu in enumerate(gpu_inventory)
        }
        by_slot = {
            self.normalize_interface(gpu.get("Interface")): str(gpu.get("DeviceClass") or "").strip().lower()
            for gpu in gpu_inventory
            if self.normalize_interface(gpu.get("Interface"))
        }
        by_card = {
            str(gpu.get("Card") or "").strip().lower(): str(gpu.get("DeviceClass") or "").strip().lower()
            for gpu in gpu_inventory
            if str(gpu.get("Card") or "").strip()
        }
        if telemetry is not None:
            for source in getattr(telemetry, "_gpu_sources", []):
                try:
                    gpu_index = int(source.get("gpu_index", 0))
                except Exception:
                    continue
                slot = self.normalize_interface(source.get("slot"))
                card = str(source.get("card") or "").strip().lower()
                if slot in by_slot:
                    classes_by_index[gpu_index] = by_slot[slot]
                elif card in by_card:
                    classes_by_index[gpu_index] = by_card[card]
        return classes_by_index

    def targeting_details(
        self,
        window: Any,
        gpu_names: Dict[int, str],
        gpu_order: Dict[int, int],
        samples: List[Any],
        gpu_inventory: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        def new_info(gpu_index: int, targeted: bool) -> Dict[str, Any]:
            return {
                "GpuIndex": gpu_index,
                "Name": self.display_name(gpu_index, gpu_names),
                "DisplayName": self.duplicate_safe_name(self.display_name(gpu_index, gpu_names), gpu_index, gpu_order),
                "InventoryOrder": int(gpu_order.get(gpu_index, gpu_index)),
                "Targeted": targeted,
                "ObservationRole": "targeted" if targeted else "observed_only",
                "TargetIds": [],
                "Cards": [],
                "Slots": [],
                "Workloads": [],
                "Backends": [],
                "ResolvedDeviceNames": [],
                "ObservedInTelemetry": False,
                "WorkerEvidence": {
                    "WorkerResultCount": 0,
                    "SuccessfulWorkerResultCount": 0,
                    "WorkerErrorCount": 0,
                    "VerificationPasses": 0,
                    "MaxAllocatedVramBytes": None,
                    "MaxTargetVramBytes": None,
                    "MaxAllocationPercent": None,
                    "Backends": [],
                    "Workloads": [],
                },
            }

        per_gpu: Dict[int, Dict[str, Any]] = {}
        inventory_by_slot = {
            self.normalize_interface(gpu.get("Interface")): (index, gpu)
            for index, gpu in enumerate(gpu_inventory or [])
            if self.normalize_interface(gpu.get("Interface"))
        }
        inventory_by_card = {
            str(gpu.get("Card") or "").strip().lower(): (index, gpu)
            for index, gpu in enumerate(gpu_inventory or [])
            if str(gpu.get("Card") or "").strip()
        }
        all_workers = [*window.gpu_workers_initial, *window.gpu_workers_final]
        for worker in all_workers:
            try:
                gpu_index = int(worker.get("gpu_index", 0))
            except Exception:
                gpu_index = 0
            info = per_gpu.setdefault(gpu_index, new_info(gpu_index, True))
            info["Targeted"] = True
            info["ObservationRole"] = "targeted"
            for field_name, source_key in (
                ("TargetIds", "target_id"),
                ("Cards", "card"),
                ("Slots", "slot"),
                ("Workloads", "workload"),
                ("Backends", "backend"),
                ("ResolvedDeviceNames", "resolved_device_name"),
            ):
                value = str(worker.get(source_key, "") or "").strip()
                if value and value not in info[field_name]:
                    info[field_name].append(value)
        for payload in window.worker_results:
            if str(payload.get("kind") or "").lower() != "gpu":
                continue
            try:
                gpu_index = int(payload.get("target_gpu_index", payload.get("gpu_index", 0)) or 0)
            except Exception:
                gpu_index = 0
            info = per_gpu.setdefault(gpu_index, new_info(gpu_index, True))
            info["Targeted"] = True
            info["ObservationRole"] = "targeted"
            for field_name, source_key in (
                ("TargetIds", "target_id"),
                ("Cards", "target_card"),
                ("Slots", "target_slot"),
                ("Backends", "backend"),
            ):
                value = str(payload.get(source_key, "") or "").strip()
                if value and value not in info[field_name]:
                    info[field_name].append(value)
            workload = str(payload.get("mode") or payload.get("workload") or "").strip()
            if workload and workload not in info["Workloads"]:
                info["Workloads"].append(workload)
            resolved_name = str(
                payload.get("selected_device_name")
                or payload.get("renderer")
                or ""
            ).strip()
            if resolved_name and resolved_name not in info["ResolvedDeviceNames"]:
                info["ResolvedDeviceNames"].append(resolved_name)
            evidence = info["WorkerEvidence"]
            evidence["WorkerResultCount"] += 1
            if str(payload.get("status") or "").lower() in {"ok", "pass", "passed", "success"}:
                evidence["SuccessfulWorkerResultCount"] += 1
            evidence["WorkerErrorCount"] += self._worker_integrity_error_count([payload])
            try:
                evidence["VerificationPasses"] += int(payload.get("verification_passes") or 0)
            except Exception:
                pass
            backend = str(payload.get("backend") or "").strip()
            if backend and backend not in evidence["Backends"]:
                evidence["Backends"].append(backend)
            if workload and workload not in evidence["Workloads"]:
                evidence["Workloads"].append(workload)
            allocated = payload.get("allocated_vram_bytes", payload.get("buffer_allocation_bytes"))
            target = payload.get("active_target_vram_bytes", payload.get("target_vram_bytes", payload.get("target_buffer_bytes")))
            if isinstance(allocated, (int, float)):
                current = evidence.get("MaxAllocatedVramBytes")
                evidence["MaxAllocatedVramBytes"] = int(max(float(current or 0), float(allocated)))
            if isinstance(target, (int, float)):
                current = evidence.get("MaxTargetVramBytes")
                evidence["MaxTargetVramBytes"] = int(max(float(current or 0), float(target)))
            if isinstance(evidence.get("MaxAllocatedVramBytes"), int) and isinstance(evidence.get("MaxTargetVramBytes"), int) and evidence["MaxTargetVramBytes"] > 0:
                evidence["MaxAllocationPercent"] = round(
                    evidence["MaxAllocatedVramBytes"] / evidence["MaxTargetVramBytes"] * 100.0,
                    4,
                )
        observed_gpu_indices = self.observed_indices(samples)
        for gpu_index in observed_gpu_indices:
            info = per_gpu.setdefault(gpu_index, new_info(gpu_index, False))
            info["ObservedInTelemetry"] = True
        for gpu_index, info in per_gpu.items():
            resolved_inventory: Optional[tuple[int, Dict[str, Any]]] = None
            for slot_value in [*info.get("Slots", []), *info.get("TargetIds", [])]:
                slot = self.normalize_interface(slot_value)
                if slot in inventory_by_slot:
                    resolved_inventory = inventory_by_slot[slot]
                    break
            if resolved_inventory is None:
                for card_value in info.get("Cards", []):
                    card = str(card_value or "").strip().lower()
                    if card in inventory_by_card:
                        resolved_inventory = inventory_by_card[card]
                        break
            if resolved_inventory is None:
                continue
            inventory_index, gpu = resolved_inventory
            name = str(gpu.get("Name") or gpu.get("GpuModel") or info.get("Name") or f"GPU {gpu_index}")
            info["Name"] = name
            info["InventoryOrder"] = inventory_index
            info["DisplayName"] = self.duplicate_safe_name(name, gpu_index, {gpu_index: inventory_index})
        return [
            per_gpu[index]
            for index in sorted(
                per_gpu,
                key=lambda gpu_index: (
                    int(per_gpu[gpu_index].get("InventoryOrder", gpu_order.get(gpu_index, gpu_index))),
                    gpu_index,
                ),
            )
        ]

    def observed_indices(self, samples: List[Any]) -> List[int]:
        indices = {
            self.index_from_key(key)
            for sample in samples
            for key in sample.values.keys()
            if key.startswith("gpu_")
        }
        return sorted(indices)

    def export_sort_key(self, gpu_index: int, gpu_order: Dict[int, int]) -> tuple[int, int]:
        return (int(gpu_order.get(gpu_index, gpu_index)), gpu_index)

    def normalize_interface(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        parts = text.split(":")
        if len(parts) == 3 and len(parts[0]) == 8:
            return f"{parts[0][-4:]}:{parts[1]}:{parts[2]}"
        if len(parts) == 3 and len(parts[0]) == 4:
            return text
        if len(parts) == 2:
            return f"0000:{text}"
        return text

    def display_name(self, gpu_index: int, gpu_names: Dict[int, str]) -> str:
        return gpu_names.get(gpu_index, f"GPU {gpu_index}")

    def duplicate_safe_name(self, name: str, gpu_index: int, gpu_order: Optional[Dict[int, int]] = None) -> str:
        order = gpu_order or {}
        display_index = int(order.get(gpu_index, gpu_index)) + 1
        text = str(name or f"GPU {gpu_index}").strip()
        if re.search(r"\s#\d+$", text):
            return text
        return f"{text} #{display_index}"

    def index_from_key(self, key: str) -> int:
        try:
            return int(key.removeprefix("gpu_").split("_", 1)[0])
        except Exception:
            return 0
