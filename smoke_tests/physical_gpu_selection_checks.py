"""Physical Stage Overrides in actual CLI/TUI paths; no hardware execution."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import asyncio
import contextlib
import io

from Modules.lvs_gpu_targets import gpu_targets, physical_gpu_choices
from Modules.lvs_stage_configuration import stage_settings
from smoke_tests.configuration_workflow_checks import ROOT, Service
from smoke_tests.cli_configuration_checks import Host


def run_physical_gpu_selection_checks():
    cards = [
        dict(slot="0000:07:00.0", physical_gpu_id="pci:0000:07:00.0", name="Radeon 610M", card="card0", device_class="integrated"),
        dict(slot="0000:41:00.0", physical_gpu_id="pci:0000:41:00.0", name="RTX PRO Max-Q", card="card1", nvidia_uuid="GPU-a"),
        dict(slot="0000:82:00.0", physical_gpu_id="pci:0000:82:00.0", name="RTX PRO Max-Q", card="card2", nvidia_uuid="GPU-b"),
    ]
    selection = "slots:0000:07:00.0"
    for order in (cards, list(reversed(cards))):
        assert gpu_targets(selection, order) == [cards[0]]
        assert gpu_targets("slots:0000:82:00.0", order) == [cards[2]]
        assert gpu_targets("slots:0000:41:00.0,0000:82:00.0", order) == cards[1:]
        choices = dict(physical_gpu_choices(order))
        assert "Radeon 610M" in choices[selection] and "0000:07:00.0" in choices[selection]
        assert len(choices) == 3
        assert gpu_targets("all", order) == order
        # Preserve existing generic semantics; never reinterpret primary/first.
        for generic in ("primary", "first"):
            assert gpu_targets(generic, order) == order
    for invalid, inventory in (
        (selection, []), (selection, cards + [dict(cards[0])]),
        (selection, [dict(cards[0], physical_gpu_id="pci:0000:08:00.0")]),
        ("slots:0000:41:00.0", [*cards, dict(cards[2], nvidia_uuid="GPU-a")]),
        (selection, [dict(cards[0], render_node="/dev/dri/renderD128"), dict(cards[1], render_node="/dev/dri/renderD128")]),
        ("slots:0000:07:00.0,0000:99:00.0", cards),
        ("slots:0000:07:00.0,0000:07:00.0", cards),
        ("slots:", cards), ("slots:card0", cards),
    ):
        try: gpu_targets(invalid, inventory)
        except ValueError as exc: assert str(exc)
        else: raise AssertionError(f"unsafe physical selection accepted: {invalid} {inventory}")
    assert not physical_gpu_choices([dict(name="GPU", card="card0")])

    def prepare(root):
        service = Service(root)
        inventory = deepcopy(cards)
        service.orchestrator = SimpleNamespace(workload_runner=SimpleNamespace(_discover_gpu_cards=lambda: inventory))
        profile = service.profile_loader.load_profile(ROOT / "profiles/GPU Vulkan Memory Lab.json")
        profile.stages[0].modules.vram.enabled = True
        source = Path(service.settings.profiles_dir) / "Physical Selection.json"
        service.profile_loader.save_profile(source, profile)
        return service, inventory, source

    with TemporaryDirectory(dir=ROOT) as tmp, contextlib.redirect_stdout(io.StringIO()) as output:
        service, inventory, source = prepare(Path(tmp)); before = source.read_bytes()
        setup = service.create_run_setup(source); edit = service.run_setup_stage_edit(setup)
        fields = service.stage_configuration_settings(edit, 0)
        field = next(f for f in fields if f.key == "gpu_3d_target")
        assert field.options[:4] == tuple(service.profile_editor.GPU_TARGET_OPTIONS)
        # CLI uses the same catalog and transactional mutation as TUI/service.
        answers = [str(fields.index(field)+1), str(field.options.index(selection)+1), ""]
        host = Host(service, answers)
        host.profile_cli.configure_stage_workloads(setup.profile, 0, setup.labels, run_only=True)
        assert "Radeon 610M | PCI 0000:07:00.0" in output.getvalue()
        assert setup.profile.stages[0].modules.gpu_3d.gpus == selection
        other = service.create_run_setup(source); other_edit = service.run_setup_stage_edit(other)
        service.apply_stage_configuration(other_edit, 0, "gpu_3d_target", selection)
        other.profile = other_edit.profile
        assert service.profile_loader.profile_payload(other.profile) == service.profile_loader.profile_payload(setup.profile)
        service.apply_stage_configuration(edit, 0, "vram_target", "slots:0000:82:00.0")
        assert edit.profile.stages[0].modules.vram.gpus == "slots:0000:82:00.0"
        # Real capture serialization/report formatting retain the physical slot.
        assert selection in "\n".join(__import__('Modules.lvs_stage_configuration', fromlist=['effective_stage_text']).effective_stage_text(setup.profile.stages[0]))
        captured = Path(tmp) / "profile_used.json"
        service.profile_loader.save_profile(captured, setup.profile)
        loaded = service.profile_loader.load_captured_profile(captured)
        assert gpu_targets(loaded.stages[0].modules.gpu_3d.gpus, list(reversed(inventory))) == [cards[0]]
        assert source.read_bytes() == before
        assert service.create_run_setup(source).profile.stages[0].modules.gpu_3d.gpus == "all"
        # Hot-unplug between display and commit must reject without mutation.
        inventory.clear(); previous = deepcopy(edit.profile)
        try: service.apply_stage_configuration(edit, 0, "gpu_3d_target", selection)
        except ValueError as exc: assert "unavailable or ambiguous" in str(exc)
        else: raise AssertionError("missing GPU accepted after picker display")
        assert edit.profile == previous
        inventory.extend(cards)
        for generic in service.profile_editor.GPU_TARGET_OPTIONS:
            service.apply_stage_configuration(edit, 0, "gpu_3d_target", generic)
        assert source.read_bytes() == before

    try:
        from Modules.lvs_tui_app import LinuxValidationSuiteTui
    except ModuleNotFoundError as exc:
        if exc.name != "textual": raise
        print("SKIP optional Textual pilot; CLI/service assertions passed")
        return

    class App(LinuxValidationSuiteTui):
        def _refresh_live_system_pane(self): pass

    async def check():
        with TemporaryDirectory(dir=ROOT) as tmp:
            service, inventory, source = prepare(Path(tmp)); before = source.read_bytes()
            app = App(service)
            async with app.run_test(size=(150, 55)) as pilot:
                await pilot.pause()
                await app.action_setup_run()
                await app._handle_stage_override_choice("Configure Stage Workloads (this run only)")
                await app._select_setup_picker_option(app.setup_picker_options[0])
                field_index = next(i for i, f in enumerate(app.stage_configuration_fields) if f.key == "gpu_3d_target")
                await app._activate_stage_configuration_item(field_index+1)
                assert selection in app.profile_edit_picker_options
                app.query_one("#items").index = app.profile_edit_picker_options.index(selection)
                await pilot.press("enter"); await pilot.pause()
                assert app.run_setup.profile.stages[0].modules.gpu_3d.gpus == selection
                assert app.run_setup.profile.stages[0].modules.vram.gpus == "all"
                await app._activate_stage_configuration_item(field_index+1)
                await pilot.press("escape"); await pilot.pause()
                assert app.run_setup.profile.stages[0].modules.gpu_3d.gpus == selection
                assert source.read_bytes() == before
                assert service.create_run_setup(source).profile.stages[0].modules.gpu_3d.gpus == "all"
    asyncio.run(check())
