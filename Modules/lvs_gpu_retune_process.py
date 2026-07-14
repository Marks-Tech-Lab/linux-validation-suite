from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, Optional, Tuple

from Modules.lvs_core import now_local_iso
from Modules.lvs_gpu_worker_plan import GpuWorkerSpec
from Modules.lvs_run_lifecycle import phase_line
from Modules.lvs_stage_process_control import StageProcess


def replace_gpu_process_for_retune(
    *,
    entry: StageProcess,
    new_spec: GpuWorkerSpec,
    display_name: str,
    metric_summary: str,
    command_env: Dict[str, str],
    serialize_worker: Callable[[GpuWorkerSpec], Dict[str, Any]],
    popen_factory: Callable[..., Any] = subprocess.Popen,
    print_func: Callable[[str], None] = print,
) -> Tuple[Optional[StageProcess], Optional[Dict[str, Any]]]:
    previous_spec = entry.gpu_spec
    if previous_spec is None:
        return None, None
    try:
        entry.process.terminate()
        entry.process.wait(timeout=5)
    except Exception:
        try:
            entry.process.kill()
        except Exception:
            pass
    try:
        new_process = popen_factory(
            new_spec.command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=command_env,
        )
    except Exception as exc:
        print_func(
            f"[warn] Failed to retune GPU worker {previous_spec.target_id or previous_spec.card} on stage {display_name}: {exc}"
        )
        return None, None
    event = {
        "timestamp": now_local_iso(),
        "stage": display_name,
        "target_id": previous_spec.target_id or previous_spec.card,
        "workload": previous_spec.workload,
        "previous_tuning_step": previous_spec.tuning_step,
        "new_tuning_step": new_spec.tuning_step,
        "metric_summary": metric_summary,
        "previous_worker": serialize_worker(previous_spec),
        "new_worker": serialize_worker(new_spec),
    }
    metric_key = "busy" if previous_spec.workload == "gpu_3d" else "vram"
    metric_value = metric_summary.split("=", 1)[1] if "=" in metric_summary else metric_summary
    print_func(
        phase_line(
            event["timestamp"],
            "gpu-retune",
            stage=display_name,
            target=previous_spec.target_id or previous_spec.card,
            workload=previous_spec.workload,
            step=new_spec.tuning_step,
            **{metric_key: metric_value},
        )
    )
    return (
        StageProcess(
            kind=entry.kind,
            command=new_spec.command,
            process=new_process,
            gpu_spec=new_spec,
            result_path=entry.result_path,
        ),
        event,
    )
