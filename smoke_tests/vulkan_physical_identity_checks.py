"""Rejection-capable UUID/PCI fixtures from the three-GPU physical capture."""
from copy import deepcopy
import ctypes
from itertools import permutations
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from smoke_tests.vulkan_workload_effectiveness_checks import _worker_payload
from smoke_tests.gpu_slow_operation_checks import _artifact_round_trip

from Modules.lvs_vulkan_identity import (
    PhysicalDeviceIDProperties, PhysicalDeviceProperties2, normalize_device_uuid,
    identity_instance_api_version, read_device_uuid, supports_pci_bus_info, physical_identity_match,
)
from Modules.lvs_vulkan_targeting import vulkan_device_for_target
from Modules.lvs_vulkan_runtime import merge_vulkan_device_inventories
from Modules.lvs_gpu_backend_support import vulkan_backend_target_support
from Modules.lvs_gpu_backend_resolver import resolve_gpu_backend_for_targets, gpu_backend_support_summary
from Modules.lvs_compat_export_helpers import preserve_legacy_worker_evidence_contract
from Modules.lvs_compat_export_gpu import build_gpu_worker_validation_detail
from vulkan_transfer_worker import score_device


def _fixtures():
    captured = [
        ("0000:41:00.0", "2bb4", "9553885d-5f15-11ff-6dc9-ec67c1459aee"),
        ("0000:82:00.0", "2bb4", "3da1b386-290e-a5db-d6ca-df696c8c5b9a"),
        ("0000:81:00.0", "2bb1", "70be56b3-92b6-d9c9-65ea-37d0659306b8"),
    ]
    cards = [dict(slot=slot, target_id=slot, physical_gpu_id="pci:" + slot,
                  vendor="NVIDIA", vendor_id="10de", device=part, nvidia_uuid="GPU-" + identifier)
             for slot, part, identifier in captured]
    devices = [dict(index=i, vendorID="0x10de", deviceID="0x" + part,
                    deviceName="duplicate" if part == "2bb4" else "other",
                    deviceType="PHYSICAL_DEVICE_TYPE_DISCRETE_GPU", deviceUUID=identifier)
               for i, (_, part, identifier) in enumerate(captured)]
    return cards, devices


def run_vulkan_fail_closed_checks():
    cards, devices = _fixtures()
    target = cards[1]
    wrong = deepcopy(devices[0])
    wrong.pop("deviceUUID")
    result = vulkan_device_for_target([wrong], target, gpu_cards=cards,
        likely_discrete_ids={card["target_id"] for card in cards})
    assert not result["available"], "sole unbound wrong-device candidate must not pass planning"
    fabricated = {"available": True, "ambiguous": False, "device": wrong}
    preflight = vulkan_backend_target_support(backend="python_vulkan_compute", target=target,
        workload="gpu_3d", vulkan_match=fabricated)
    assert not preflight["supported"] and preflight["physical_identity_status"] == "missing_evidence"
    args = SimpleNamespace(target_device_uuid="", target_vendor_id="10de", target_device_id="2bb4",
        target_vendor="NVIDIA", target_device_name="duplicate", target_slot=target["slot"],
        target_id=target["target_id"], device_class="discrete", vulkan_device_index=0, target_gpu_index=1)
    info = dict(index=0, device_uuid=devices[0]["deviceUUID"], pci_slot="", vendor_id="10de",
        device_id="2bb4", device_name="duplicate", device_type="discrete")
    assert score_device(info, args) < -1000, "the former 2690-score wrong device must be rejected"
    from vulkan_transfer_worker import select_physical_device as transfer_select
    from vulkan_compute_worker import select_physical_device as compute_select
    from Modules.lvs_vulkan_workers import build_python_vulkan_compute_worker, build_python_vulkan_transfer_worker

    def rejects(call):
        try:
            call()
        except (RuntimeError, ValueError):
            return
        raise AssertionError("unsafe physical target was accepted")

    for selector in (compute_select, transfer_select):
        rejects(lambda: selector([(info, "wrong_handle")], args))
        bound = SimpleNamespace(**{**vars(args), "target_device_uuid": target["nvidia_uuid"]})
        rejects(lambda: selector([(info, "wrong_handle")], bound))
        # Known UUID is absent from the runtime: only a real PCI match can
        # authorize execution, including a device without core 1.1 UUIDs.
        right_pci = dict(info, device_uuid="", pci_slot=target["slot"])
        assert selector([(right_pci, "right_handle")], bound)[2] == "right_handle"
        assert selector([(right_pci, "right_handle")], args)[2] == "right_handle"
        rejects(lambda: selector([(dict(right_pci, device_uuid=devices[0]["deviceUUID"]), "wrong")], bound))
        correct = dict(info, device_uuid=devices[1]["deviceUUID"], pci_slot=target["slot"])
        assert selector([(info, "wrong"), (correct, "right")], bound)[2] == "right"
        assert selector([(correct, "right"), (info, "wrong")], bound)[2] == "right"
        rejects(lambda: selector([(correct, "a"), (correct, "b")], bound))
        for invalid in ["malformed", "00000000-0000-0000-0000-000000000000"]:
            rejects(lambda: selector([(dict(correct, device_uuid=invalid), "wrong")], bound))
        inconsistent = SimpleNamespace(**{**vars(bound), "physical_gpu_id": "pci:" + cards[0]["slot"]})
        rejects(lambda: selector([(correct, "wrong")], inconsistent))

    for requested_uuid in ("", target["nvidia_uuid"]):
        requested = dict(target)
        if not requested_uuid:
            requested.pop("nvidia_uuid")
        for wrong_candidate in (wrong, devices[0]):
            match = vulkan_device_for_target([wrong_candidate], requested, gpu_cards=cards,
                likely_discrete_ids={c["target_id"] for c in cards})
            assert not match["available"]
    assert physical_identity_match("", "", "", "")["status"] == "unknown_identity"
    assert physical_identity_match(target["nvidia_uuid"], target["slot"], "", "")["status"] == "missing_evidence"
    assert physical_identity_match(target["nvidia_uuid"], target["slot"], devices[0]["deviceUUID"], "")["status"] == "conflicting_identity"

    class Runner:
        def __init__(self, device): self.device = device
        def _python_runtime(self): return "python3"
        def _gpu_worker_tuned_params(self, *_args, **_kwargs): return {"capability": {"device_class": "discrete"}}
        def _gpu_internal_ramp_params(self): return {"ramp_step_seconds": 15, "start_load_fraction": 0.35}
        def _vulkan_device_for_target(self, _target): return {"available": True, "ambiguous": False, "device": self.device}
        def _vulkan_transfer_buffer_bytes(self, *_args): return 1024 * 1024
        def _vulkan_compute_buffer_bytes(self, *_args, **_kwargs): return 1024 * 1024
        def _vulkan_compute_rounds(self, *_args): return 8
        def _vulkan_compute_dispatch_repeats(self, *_args): return 4
        def _normalize_vulkan_compute_variant(self, value): return value
        def _normalize_gpu_3d_intensity(self, value): return value
        def _vulkan_target_env(self, _target): return {}
        def _wrap_gpu_command(self, command, *_args): return command

    for builder in (build_python_vulkan_compute_worker, build_python_vulkan_transfer_worker):
        rejects(lambda: builder(Runner(wrong), target))
        rejects(lambda: builder(Runner(devices[0]), target))
        # Optional candidate UUID missing, but authoritative PCI exists:
        # commands must retain the known requested UUID, never replace it with ''.
        right = dict(devices[1], pci_slot=target["slot"])
        right.pop("deviceUUID")
        spec = builder(Runner(right), target)
        command = spec.command
        assert command[command.index("--target-device-uuid") + 1] == devices[1]["deviceUUID"]
        assert command[command.index("--target-slot") + 1] == target["slot"]
        rejects(lambda: builder(Runner(dict(right, deviceUUID=devices[0]["deviceUUID"])), target))


def run_vulkan_physical_identity_checks():
    cards, devices = _fixtures()
    def match(target, ds=devices, cs=cards):
        return vulkan_device_for_target(ds, target, gpu_cards=cs,
                                        likely_discrete_ids={c["target_id"] for c in cs})

    # Both provider orders and the API ordinals may change independently.
    for ds in permutations(devices):
        for cs in permutations(cards):
            for card in cs:
                result = match(card, list(ds), list(cs))
                assert result["available"] and not result["ambiguous"]
                assert result["device"]["pci_slot"] == card["slot"]
                assert result["device"]["deviceUUID"] == card["nvidia_uuid"][4:]
                assert result["device"]["identity_match_source"] == "nvidia_device_uuid"

    # These are UUID bytes in display order, not a little-endian GUID and not
    # driverUUID or pipelineCacheUUID. Opaque/MIG/zero identifiers are absent.
    assert normalize_device_uuid(cards[0]["nvidia_uuid"].upper()) == devices[0]["deviceUUID"]
    for value in [None, "", "GPU-not-a-uuid", "MIG-" + devices[0]["deviceUUID"], "0" * 32,
                  "00000000-0000-0000-0000-000000000000"]:
        assert normalize_device_uuid(value) == ""

    absent = deepcopy(devices)
    for d in absent:
        d.pop("deviceUUID")
        d["driverUUID"] = devices[0]["deviceUUID"]
    assert not match(cards[0], absent)["available"]
    assert match(cards[0], absent)["identity_status"] == "missing_evidence"
    assert not match(cards[2], absent)["available"]  # a unique model is not physical proof
    no_provider_uuid = [{k: v for k, v in c.items() if k != "nvidia_uuid"} for c in cards]
    assert not match(no_provider_uuid[0], devices, no_provider_uuid)["available"]
    pci_only = deepcopy(absent)
    for d, c in zip(pci_only, cards):
        d["pci_slot"] = c["slot"]
    assert match(cards[1], pci_only)["device"]["pci_slot"] == cards[1]["slot"]
    partial = deepcopy(cards)
    partial[1].pop("nvidia_uuid")
    assert match(partial[1], pci_only, partial)["device"]["pci_slot"] == partial[1]["slot"]
    assert match(cards[0], [devices[0]], [cards[0]])["available"]
    uuid_only = {"vulkan_device_uuid": devices[0]["deviceUUID"]}
    assert match(uuid_only, [devices[0]], [])["available"], "positive UUID proof needs no model or index"

    conflict = deepcopy(devices)
    conflict[0]["pci_slot"] = cards[1]["slot"]
    assert not match(cards[0], conflict)["available"]
    duplicate = deepcopy(cards)
    duplicate[1]["nvidia_uuid"] = duplicate[0]["nvidia_uuid"]
    assert not match(cards[0], devices, duplicate)["available"]
    missing_pci = deepcopy(cards)
    missing_pci[0]["slot"] = ""
    assert not match(cards[0], devices, missing_pci)["available"]
    conflict = deepcopy(devices)
    conflict[0]["deviceID"] = "0x2bb1"
    assert not match(cards[0], conflict)["available"]
    assert not match(cards[0], devices + [deepcopy(devices[0])])["available"]
    conflict = deepcopy(devices)
    conflict[0]["deviceUUID"] = "11111111-1111-1111-1111-111111111111"
    assert not match(cards[0], conflict)["available"]
    rejected = vulkan_backend_target_support(backend="python_vulkan_compute", target=cards[0],
        workload="gpu_3d", vulkan_match=match(cards[0], conflict))
    assert not rejected["supported"] and "conflicting" in rejected["reason"]

    # Merge native allocation capabilities by exact UUID, not model/order.
    native = deepcopy(devices)
    for i, d in enumerate(native):
        d["device_local_heap_bytes"] = i + 1
    merged = merge_vulkan_device_inventories(devices, list(reversed(native)))
    assert len(merged) == 3
    assert [d["device_local_heap_bytes"] for d in merged] == [1, 2, 3]

    # Auto remains whole-target-set fallback; explicit Vulkan cannot relabel
    # an ambiguous launch as supported or silently pick one duplicate card.
    def support(backend, target, workload):
        return vulkan_backend_target_support(backend=backend, target=target, workload=workload,
            vulkan_match=match(target, absent if backend == "python_vulkan_compute" else devices)) if backend == "python_vulkan_compute" else {"supported": True, "target_label": target["slot"]}
    auto = resolve_gpu_backend_for_targets(candidates=["python_vulkan_compute", "python_egl_gles2"],
        targets=cards, workload="gpu_3d", backend_available=lambda *_: True,
        support_summary=lambda backend, targets, workload: gpu_backend_support_summary(
            backend=backend, targets=targets, workload=workload, target_support=support))
    assert auto["backend"] == "python_egl_gles2"
    explicit = resolve_gpu_backend_for_targets(candidates=["python_vulkan_compute"],
        targets=cards, workload="gpu_3d", backend_available=lambda *_: True,
        support_summary=lambda backend, targets, workload: gpu_backend_support_summary(
            backend=backend, targets=targets, workload=workload, target_support=support))
    assert explicit["backend"] == "none" and not explicit["support"]
    resolved = resolve_gpu_backend_for_targets(candidates=["python_vulkan_compute", "python_egl_gles2"],
        targets=cards, workload="gpu_3d", backend_available=lambda *_: True,
        support_summary=lambda backend, targets, workload: gpu_backend_support_summary(
            backend=backend, targets=targets, workload=workload,
            target_support=lambda b, t, w: vulkan_backend_target_support(
                backend=b, target=t, workload=w, vulkan_match=match(t))))
    assert resolved["backend"] == "python_vulkan_compute" and resolved["support"]["supported"]

    # Runtime revalidates the exact UUID. A stale index cannot redirect work;
    # missing optional ID support rejects the request instead of using a name.
    args = SimpleNamespace(target_vendor_id="10de", target_device_id="2bb4", target_vendor="NVIDIA",
        target_device_name="duplicate", vulkan_device_index=0, target_gpu_index=0,
        target_slot=cards[1]["slot"], target_id=cards[1]["slot"], device_class="discrete",
        target_device_uuid=devices[1]["deviceUUID"])
    infos = [dict(index=i, device_uuid=d["deviceUUID"], pci_slot="", vendor_id="10de",
                  device_id=d["deviceID"][2:], device_name=d["deviceName"], device_type="discrete")
             for i, d in enumerate(devices)]
    assert score_device(infos[1], args) > 0
    assert score_device(infos[0], args) < -1000
    assert score_device(dict(infos[1], device_uuid=""), args) < -1000
    assert score_device(dict(infos[1], pci_slot=cards[0]["slot"]), args) < -1000
    assert score_device(dict(infos[1], device_id="2bb1"), args) < -1000
    args.target_device_uuid = ""
    args.target_slot = args.target_id = ""
    assert score_device(infos[0], args) == score_device(infos[1], args)
    assert score_device(infos[0], args) < -1000

    # ABI/optional function fixture: write all sixteen UUID bytes through the
    # real ctypes pNext, checking non-little-endian decoding and API gating.
    class Function:
        def __init__(self, call): self.call = call
        def __call__(self, *args): return self.call(*args)
    def query(_device, pointer):
        props = ctypes.cast(pointer, ctypes.POINTER(PhysicalDeviceProperties2)).contents
        assert props.sType == 1000059001
        ids = ctypes.cast(props.pNext, ctypes.POINTER(PhysicalDeviceIDProperties)).contents
        assert ids.sType == 1000071004
        ids.deviceUUID[:] = bytes.fromhex(devices[0]["deviceUUID"].replace("-", ""))
    vk = SimpleNamespace(vkGetPhysicalDeviceProperties2=Function(query))
    v11 = (1 << 22) | (1 << 12)
    assert read_device_uuid(vk, None, v11, v11) == devices[0]["deviceUUID"]
    assert read_device_uuid(vk, None, 1 << 22, v11) == ""
    assert read_device_uuid(vk, None, v11, 1 << 22) == ""
    assert read_device_uuid(SimpleNamespace(), None, v11, v11) == ""
    assert identity_instance_api_version(SimpleNamespace()) == 1 << 22
    assert not supports_pci_bus_info(SimpleNamespace(), None)
    assert not supports_pci_bus_info(SimpleNamespace(vkEnumerateDeviceExtensionProperties=Function(lambda *_: -1)), None)
    def version(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value = v11
        return 0
    assert identity_instance_api_version(SimpleNamespace(vkEnumerateInstanceVersion=Function(version))) == v11

    worker = dict(kind="gpu", backend="python_vulkan_compute", status="ok", error_count=0,
                  target_device_uuid=devices[0]["deviceUUID"], selected_device_uuid=devices[0]["deviceUUID"])
    retained = preserve_legacy_worker_evidence_contract(worker)
    assert retained["selected_device_uuid"] == worker["selected_device_uuid"]
    detail = build_gpu_worker_validation_detail(payload=worker, stage_name="GPU", stage_type="Combined",
        stage_verdict="pass", backend_name="python_vulkan_compute", device_name="duplicate")
    assert detail["SelectedDeviceUuid"] == worker["selected_device_uuid"]
    legacy = dict(worker)
    del legacy["selected_device_uuid"]
    del legacy["target_device_uuid"]
    detail = build_gpu_worker_validation_detail(payload=legacy, stage_name="GPU", stage_type="Combined",
        stage_verdict="pass", backend_name="python_vulkan_compute", device_name="duplicate")
    assert "SelectedDeviceUuid" not in detail
    # Exercise the normal manifest -> parsed/extended -> compatibility path,
    # retaining the same UUID binding alongside the existing stall contract.
    from vulkan_compute_worker import SlowOperationRecorder
    worker = _worker_payload()
    worker.update(target_device_uuid=devices[0]["deviceUUID"], selected_device_uuid=devices[0]["deviceUUID"])
    proof = physical_identity_match(devices[0]["deviceUUID"], cards[0]["slot"],
        devices[0]["deviceUUID"], cards[0]["slot"])
    worker.update(target_id=cards[0]["slot"], physical_gpu_id=cards[0]["physical_gpu_id"],
        physical_identity_evidence=proof)
    SlowOperationRecorder(worker)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _artifact_round_trip(worker, root)
        for filename in ["run_manifest.json", "parsed_results_custom.json", "parsed_results_extended.json"]:
            found = []
            identity_proofs = []
            def inspect(value):
                if isinstance(value, dict):
                    if "selected_device_uuid" in value:
                        found.append(value["selected_device_uuid"])
                    for key in ("physical_identity_evidence", "PhysicalIdentityEvidence"):
                        if key in value: identity_proofs.append(value[key])
                    for child in value.values(): inspect(child)
                elif isinstance(value, list):
                    for child in value: inspect(child)
            inspect(json.loads((root / filename).read_text()))
            assert found and all(identifier == devices[0]["deviceUUID"] for identifier in found), filename
            assert identity_proofs and all(p == proof for p in identity_proofs), filename
