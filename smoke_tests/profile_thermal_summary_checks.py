"""Automatic profile summaries preserve authored metadata and execution semantics."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import subprocess

from Modules.lvs_profile_edit_view import profile_stage_summary_lines, stage_enabled_module_names
from Modules.lvs_profile_models import StageConfig, ValidationProfile
from Modules.lvs_profile_report_text import profile_summary_text


def run_profile_thermal_summary_checks():
    examples = []
    for modules in (('cpu', 'gpu_3d'), ('memory', 'vram'), ()):
        stage = StageConfig('stage_1', 'Combined', 120, display_label='Power (CPU + GPU)')
        # Model defaults intentionally include other workloads, so set each explicitly.
        for name in ('cpu', 'memory', 'gpu_3d', 'vram', 'storage_benchmark', 'storage_thermal'):
            getattr(stage.modules, name).enabled = name in modules or name == 'storage_thermal'
        profile = ValidationProfile('Operator name', menu_description='Authored menu description', stages=[stage])
        for enabled, stage_enabled, ordinary, system in (
            (True, True, 50, 25), (True, True, 37, 12),
            (False, True, 50, 25), (True, False, 50, 25),
        ):
            thermal = stage.modules.storage_thermal
            thermal.enabled = enabled
            thermal.intensity_percent, thermal.system_intensity_percent = ordinary, system
            stage.enabled = stage_enabled
            before = deepcopy(asdict(profile))
            tui = '\n'.join(profile_stage_summary_lines(stage, stage.display_label, 1))
            cli = profile_summary_text(Path('operator.json'), profile, [stage.display_label], str)
            assert ('storage_thermal' in stage_enabled_module_names(stage)) is enabled
            for output in (tui, cli):
                assert ('Storage Thermal Assist requested' in output) is enabled, output
                assert 'Power (CPU + GPU)' in output
                assert 'COMPLETED' not in output and 'executed' not in output
                if enabled:
                    assert 'All Eligible Internal Drives' in output
                    assert f'ordinary {ordinary}%, system {system}%' in output
                if not stage_enabled:
                    assert 'disabled' in output
            if enabled:
                assert next(line.strip() for line in tui.splitlines() if 'Storage Thermal Assist' in line) in cli
            assert asdict(profile) == before
            examples.append(dict(modules=modules, enabled=enabled, stage_enabled=stage_enabled, tui=tui, cli=cli))
    # Load real saved profiles and prove all 41 stages retain their committed content.
    from Modules.lvs_profile_loader import ProfileLoader
    root = Path(__file__).resolve().parents[1]
    loader = ProfileLoader(root/'profiles')
    stages = 0
    for name in ('PL Validation', 'PL Validation 4hr', 'PL Validation 6hr', 'PL Validation 12hr',
                 'PL Validation 24hr', 'QA System Test Short v2', 'Power Test 5hr'):
        path = root/'profiles'/(name+'.json')
        original = path.read_bytes()
        assert original == subprocess.check_output(['git', 'show', 'HEAD:profiles/'+path.name], cwd=root)
        profile = loader.load_profile(path)
        labels = loader.load_segment_labels(path, profile)
        cli = profile_summary_text(path, profile, labels, loader.menu_group_label)
        for index, stage in enumerate(profile.stages):
            assert stage.modules.storage_thermal.enabled
            assert stage.modules.storage_thermal.intensity_percent == 50
            assert stage.modules.storage_thermal.system_intensity_percent == 25
            assert any('Storage Thermal Assist requested' in line for line in profile_stage_summary_lines(stage, labels[index], index+1))
            stages += 1
        assert cli.count('Storage Thermal Assist requested') == len(profile.stages)
        assert path.read_bytes() == original
    assert stages == 41
    plain_path = root/'profiles/Quick Test.json'
    plain = loader.load_profile(plain_path)
    assert not any(stage.modules.storage_thermal.enabled for stage in plain.stages)
    assert 'Storage Thermal Assist' not in profile_summary_text(plain_path, plain, loader.load_segment_labels(plain_path, plain), loader.menu_group_label)
    print('  automatic summaries: 12 fixture combinations; CLI/TUI request parity; authored metadata and 7 profiles/41 stages preserved')
    return examples
