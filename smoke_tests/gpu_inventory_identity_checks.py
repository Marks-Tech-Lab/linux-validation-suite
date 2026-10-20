"""Static inventory replay and rejection tests; never execute GPU workloads."""

from copy import deepcopy
from itertools import permutations
from types import SimpleNamespace
from unittest.mock import patch

from Modules.lvs_system_info import SystemInfoCollector
from Modules.lvs_gpu_export_helpers import enumerate_gpu_devices
from Modules.lvs_compat_export_gpu import build_compatibility_gpu_section


CAPACITY = 102641958912  # Provider memory.total, not an inferred Vulkan heap.


def captured_inventory():
    """Identity/type/capacity fields from the October 20 Gigabyte capture."""
    rows = [
        ("0000:41:00.0", "2bb4", "9553885d-5f15-11ff-6dc9-ec67c1459aee"),
        ("0000:82:00.0", "2bb4", "3da1b386-290e-a5db-d6ca-df696c8c5b9a"),
        ("0000:81:00.0", "2bb1", "70be56b3-92b6-d9c9-65ea-37d0659306b8"),
    ]
    drm, provider, devices = [], [], []
    for index, (slot, part, identifier) in enumerate(rows):
        name = "NVIDIA RTX PRO 6000 Blackwell " + (
            "Max-Q Workstation Edition" if part == "2bb4" else "Workstation Edition")
        drm.append(dict(card=f"card{index}", pci_slot=slot, physical_gpu_id="pci:" + slot,
                        vendor_id="10de", device_id=part, driver="nvidia", name=name, chipset=name,
                        device_class="unknown", memory_bytes=0, pcie_link={}))
        provider.append(dict(pci_slot=slot, nvidia_uuid="GPU-" + identifier, name=name,
                             driver="615.78.08", memory="95.59 GB", memory_bytes=CAPACITY))
        devices.append(dict(index=index, vendorID="0x10de", deviceID="0x" + part,
                            deviceName=name, deviceUUID=identifier,
                            deviceType="PHYSICAL_DEVICE_TYPE_DISCRETE_GPU",
                            device_local_heap_bytes=CAPACITY))
    return drm, provider, devices


class InventoryFixture(SystemInfoCollector):
    def __init__(self, drm, provider, devices):
        super().__init__()
        self.drm, self.provider, self.devices = deepcopy((drm, provider, devices))

    def _discover_drm_gpus(self):
        return deepcopy(self.drm)

    def _discover_nvidia_smi_gpus(self):
        return deepcopy(self.provider)

    def _native_vulkan_inventory(self):
        return {"available": bool(self.devices), "devices": deepcopy(self.devices)}

    def _runtime_gpu_names_by_slot(self, _gpus):
        return {}

    def _memory_total_bytes(self):
        return 256 * 1024**3

    def inventory(self):
        with patch("shutil.which", return_value=None):
            return {row["Interface"]: row for row in self._gpu_info()}


def run_gpu_inventory_identity_checks():
    drm, provider, devices = captured_inventory()
    # Every provider can enumerate independently. Neither names nor ordinals
    # supply the identity join; the two identical parts must remain distinct.
    for ordered_drm in permutations(drm):
        for ordered_provider in permutations(provider):
            for ordered_devices in permutations(devices):
                result = InventoryFixture(ordered_drm, ordered_provider, ordered_devices).inventory()
                assert len(result) == 3
                for card in drm:
                    row = result[card["pci_slot"]]
                    assert row["PhysicalGpuId"] == card["physical_gpu_id"]
                    assert row["DeviceClass"] == "discrete"
                    assert row["DeviceClassConfidence"] == "high"
                    assert row["VulkanIdentitySource"] == "nvidia_device_uuid"
                    assert row["MemoryArchitecture"] == "dedicated"
                    assert row["DedicatedMemoryBytes"] == CAPACITY
                    assert row["ProviderReportedMemorySource"] == "nvidia_smi_memory_total"
                    assert row["VulkanDeviceLocalHeapBytes"] == CAPACITY
                exported = enumerate_gpu_devices(list(result.values()))
                assert {row["PhysicalGpuId"] for row in exported} == {card["physical_gpu_id"] for card in drm}
                assert all(row["MemoryArchitecture"] == "dedicated" for row in exported)

    section = build_compatibility_gpu_section(gpu_devices=exported, segments=[], worker_metric_tests={})
    assert len(section["devices"]) == 3
    assert all(row["gpu_device_class"] == "discrete" and row["gpu_memory_architecture"] == "dedicated"
               and row["gpu_dedicated_memory_bytes"] == CAPACITY for row in section["devices"])
    assert len({row["gpu_display_name"] for row in section["devices"]}) == 3
    assert len(InventoryFixture(drm[:2], provider[:2], devices[:2]).inventory()) == 2

    collector = SystemInfoCollector()
    bound = [dict(card, nvidia_uuid=provider[i]["nvidia_uuid"]) for i, card in enumerate(drm)]
    assert all(row["DeviceClass"] == "discrete" for row in InventoryFixture(bound, [], devices).inventory().values())
    # Missing identity, even a sole matching vendor/device, is not proof.
    unbound = [dict(device, deviceUUID="") for device in devices]
    assert InventoryFixture([], [], devices)._native_vulkan_gpu_details_by_slot([]) == {}
    assert not collector._vulkan_inventory_devices_by_slot(unbound, bound)
    assert not collector._vulkan_inventory_devices_by_slot([unbound[2]], [bound[2]])
    assert not collector._vulkan_inventory_devices_by_slot(devices, drm)  # No provider UUID or runtime PCI.
    assert not InventoryFixture(drm, provider, []).inventory()[drm[0]["pci_slot"]]["DedicatedMemoryBytes"]
    assert all(row["DeviceClass"] == "unknown" for row in InventoryFixture(drm, [], devices).inventory().values())
    for altered in (
        [dict(devices[0], pci_slot=drm[1]["pci_slot"]), *devices[1:]],
        [devices[0], dict(devices[1], deviceUUID=devices[0]["deviceUUID"]), devices[2]],
        [dict(devices[0], deviceUUID="malformed"), *devices[1:]],
    ):
        assert not collector._vulkan_inventory_devices_by_slot(altered, bound)
    for altered in (
        [provider[0], dict(provider[1], nvidia_uuid=provider[0]["nvidia_uuid"]), provider[2]],
        [*provider, provider[0]],
        [dict(provider[0], nvidia_uuid="invalid"), *provider[1:]],
    ):
        assert all(row["DeviceClass"] == "unknown" for row in InventoryFixture(drm, altered, devices).inventory().values())
    conflict = deepcopy(drm)
    conflict[0]["nvidia_uuid"] = provider[1]["nvidia_uuid"]
    assert all(row["DeviceClass"] == "unknown" for row in InventoryFixture(conflict, provider, devices).inventory().values())

    # Native and vulkaninfo must not provide contradictory device types.
    fixture = InventoryFixture(drm, provider, devices)
    fixture._parse_vulkan_summary_devices = lambda _: [dict(devices[0], deviceType="INTEGRATED_GPU")]
    with patch("shutil.which", return_value="vulkaninfo"), patch(
        "Modules.lvs_system_info.subprocess.run", return_value=SimpleNamespace(stdout="fixture", stderr="")
    ):
        result = fixture._vulkan_gpu_classes_by_slot(bound)
    assert result[drm[0]["pci_slot"]]["device_class"] == "unknown"
    assert "vulkan_device_local_heap_bytes" not in result[drm[0]["pci_slot"]]

    # A native UUID and a different summary UUID cannot both describe the same
    # authoritative PCI function, even if their device-type labels agree.
    pci_device = dict(devices[0], pci_slot=drm[0]["pci_slot"])
    fixture = InventoryFixture(drm[:1], [], [pci_device])
    fixture._parse_vulkan_summary_devices = lambda _: [dict(pci_device, deviceUUID=devices[1]["deviceUUID"])]
    with patch("shutil.which", return_value="vulkaninfo"), patch(
        "Modules.lvs_system_info.subprocess.run", return_value=SimpleNamespace(stdout="fixture", stderr="")
    ):
        result = fixture._vulkan_gpu_classes_by_slot(drm[:1])
    assert result[drm[0]["pci_slot"]]["device_class_source"] == "conflicting_vulkan_identity"

    # vulkaninfo alone can provide a proven type, without inventing a heap.
    fixture = InventoryFixture(drm, provider, [])
    fixture._parse_vulkan_summary_devices = lambda _: deepcopy(devices)
    with patch("shutil.which", return_value="vulkaninfo"), patch(
        "Modules.lvs_system_info.subprocess.run", return_value=SimpleNamespace(stdout="fixture", stderr="")
    ):
        result = fixture._gpu_info()
    assert all(row["DeviceClass"] == "discrete" and row["MemoryArchitecture"] == "dedicated"
               and row["VulkanDeviceLocalHeapBytes"] is None for row in result)

    # Authoritative PCI remains sufficient without optional UUID discovery.
    for vendor, part, driver, kind in (
        ("1002", "73ff", "amdgpu", "DISCRETE"),
        ("8086", "46a6", "i915", "INTEGRATED"),
        ("10de", "2b00", "nvidia", "INTEGRATED"),
    ):
        card = dict(drm[0], vendor_id=vendor, device_id=part, driver=driver,
                    memory_bytes=CAPACITY, provider_memory_source="drm_mem_info_vram_total")
        device = dict(devices[0], vendorID=vendor, deviceID=part, deviceUUID="",
                      pci_slot=card["pci_slot"], deviceType=kind + "_GPU",
                      device_local_heap_bytes=2 * CAPACITY)
        row = InventoryFixture([card], [], [device]).inventory()[card["pci_slot"]]
        assert row["VulkanIdentitySource"] == "vulkan_pci"
        if kind == "INTEGRATED":
            assert row["MemoryArchitecture"] == "shared" and row["DedicatedMemoryBytes"] is None
        else:
            assert row["MemoryArchitecture"] == "dedicated" and row["DedicatedMemoryBytes"] == CAPACITY
        # An API heap alone does not establish a physical dedicated capacity.
        card["memory_bytes"] = 0
        row = InventoryFixture([card], [], [device]).inventory()[card["pci_slot"]]
        assert row["DedicatedMemoryBytes"] in (None, 0)
        assert row["VulkanDeviceLocalHeapBytes"] == 2 * CAPACITY

    bmc = dict(drm[0], vendor_id="1a03", device_id="2000", driver="ast", name="ASPEED Graphics Family")
    assert not InventoryFixture([bmc], [], []).inventory(), "management display remains excluded"
    software = dict(devices[0], deviceName="llvmpipe", deviceType="CPU", pci_slot=drm[0]["pci_slot"])
    assert not collector._vulkan_inventory_devices_by_slot([software], bound)

    # A PCI device with unavailable identity cannot be reassigned to a lone
    # platform GPU. Existing platform discovery remains independently usable.
    platform = dict(name="Adreno X1-45", chipset="Adreno", driver="adreno", pci_slot="", device_class="integrated",
                    physical_gpu_id="platform:3d00000.gpu", platform_gpu_driver="adreno",
                    platform_gpu_path="/sys/devices/platform/soc@0/3d00000.gpu", memory_bytes=0)
    platform_device = dict(deviceName="Adreno X1-45", deviceType="INTEGRATED_GPU", vendorID="5143",
                           deviceID="0", device_local_heap_bytes=12 * 1024**3)
    result = InventoryFixture([*drm, platform], provider, [*devices, platform_device]).inventory()
    assert result[""]["MemoryArchitecture"] == "shared"
    assert result[""]["DedicatedMemoryBytes"] is None
    assert result[""]["PhysicalGpuId"] == platform["physical_gpu_id"]
    assert not InventoryFixture([*drm, platform], [], unbound)._native_vulkan_platform_details([*drm, platform])

    # Actual NVIDIA discovery must retain UUIDs, not just the later fixture join.
    with patch("Modules.lvs_system_info.discover_nvidia_smi_gpus", return_value=[dict(
        slot=provider[0]["pci_slot"], uuid=provider[0]["nvidia_uuid"], name=provider[0]["name"], memory_mb=97887
    )]):
        assert collector._discover_nvidia_smi_gpus()[0]["nvidia_uuid"] == provider[0]["nvidia_uuid"]
