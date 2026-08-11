# Hardware Validation Profile Pack

This pack is for the consolidated x86_64 and AArch64 hardware-validation phase. Dry Run must be reviewed before every real run. A profile must not be launched when an explicit backend resolves to a different backend, when its intended GPU target set is empty, or when readiness reports a blocking issue.

## Common rules

- Sustained stages run for 600 seconds with 30-second start/end trims.
- Targeting-only stages run for 90 seconds with 10-second trims.
- RAM percentages are intent against Linux `MemTotal`; the launch-time unified planner resolves bytes from `MemAvailable`, the global reserve, and concurrent shared-GPU commitments.
- Shared GPU targets participate in the system-memory pool. Dedicated VRAM does not.
- Never disable thermal protection, verification, canaries, allocation limits, or the runtime memory guard.
- Optional profiles are run only when Dry Run selects the named backend and intended hardware target.

## Profiles and nominal sequential duration

| Profile | Stages | Duration |
| --- | ---: | ---: |
| ARM64 CPU Full Validation | 4 sustained | 40 min |
| ARM64 CPU Targeting Functional | 3 functional | 4 min 30 sec |
| ARM64 Memory Full Validation | 3 sustained | 30 min |
| ARM64 GPU Full Validation | 4 sustained | 40 min |
| ARM64 Combined Full Validation | 5 sustained | 50 min |
| x86_64 CPU Full Validation | 6 sustained | 60 min |
| x86_64 CPU AVX512 Optional Validation | 1 sustained | 10 min |
| x86_64 CPU Targeting Functional | 3 functional | 4 min 30 sec |
| x86_64 Memory Full Validation | 3 sustained | 30 min |
| x86_64 Intel iGPU Full Validation | 3 sustained | 30 min |
| x86_64 AMD APU GPU Full Validation | 3 sustained | 30 min |
| x86_64 AMD dGPU Full Validation | 3 sustained | 30 min |
| x86_64 NVIDIA dGPU Full Validation | 3 sustained | 30 min |
| x86_64 iGPU EGL Optional Validation | 1 sustained | 10 min |
| x86_64 iGPU OpenCL Optional Validation | 2 sustained | 20 min |
| x86_64 AMD dGPU OpenCL Optional Validation | 2 sustained | 20 min |
| x86_64 NVIDIA dGPU OpenCL Optional Validation | 2 sustained | 20 min |
| x86_64 Multi-GPU Combined Full Validation | 6 sustained | 60 min |

## Machine mapping

### Snapdragon AArch64 with Adreno

Run the five ARM64 profiles. The one-pass nominal duration is 164 minutes 30 seconds. For the complete CPU-targeting matrix, run the targeting profile once normally and once under each applicable one-core, sparse, and nonzero/subset cpuset wrapper; this raises the machine total to approximately 178 minutes.

Expected unavailable capabilities are OpenCL, GPU power, GPU utilization, VRAM clock, CPU clock, CPU package power, and CPU throttling. These are not failures when reported unavailable truthfully. EGL must select hardware Adreno/freedreno, not software rendering.

### Intel hybrid CPU, Intel iGPU, AMD dGPU

Run x86_64 CPU Full, CPU Targeting Functional, Memory Full, Intel iGPU Full, AMD dGPU Full, and Multi-GPU Combined. Add AVX512, iGPU EGL, iGPU OpenCL, and AMD dGPU OpenCL only when their Dry Runs select the exact requested capability. Core duration is 214 minutes 30 seconds; all optional profiles raise it to 274 minutes 30 seconds. A four-run targeting matrix raises those totals by 13 minutes 30 seconds.

### AMD APU with NVIDIA dGPU

Run x86_64 CPU Full, CPU Targeting Functional, Memory Full, AMD APU GPU Full, NVIDIA dGPU Full, and Multi-GPU Combined. Add AVX512, iGPU EGL, iGPU OpenCL, and NVIDIA dGPU OpenCL only when exact readiness succeeds. The duration ranges are the same as the Intel/AMD-dGPU class. Use this mapping for both modern and older APU generations; readiness determines optional backend availability.

## CPU targeting wrappers

The profile schema does not alter the process cpuset. Determine allowed IDs first:

```bash
.venv/bin/python -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0)))))'
```

Normal allowed-set run:

```bash
.venv/bin/python linux_validation_suite.py
```

One-core, sparse, and nonzero/subset examples use valid IDs from the preceding command:

```bash
taskset --cpu-list <one-allowed-cpu-id> .venv/bin/python linux_validation_suite.py
taskset --cpu-list <allowed-id-a>,<allowed-id-c>,<allowed-id-e> .venv/bin/python linux_validation_suite.py
taskset --cpu-list <allowed-nonzero-start>-<allowed-nonzero-end> .venv/bin/python linux_validation_suite.py
```

Select the architecture-appropriate `CPU Targeting Functional` profile inside LVS. Dry Run must show exactly the wrapper's allowed/target CPU IDs. The native stage must show common-safe Auto resolution and affinity evidence; Python must show controlled affinity evidence; stress-ng must show the authoritative taskset command without claiming per-worker affinity.

## Operator workflow for every later run

1. Launch `.venv/bin/python linux_validation_suite.py` (or the appropriate `taskset` wrapper).
2. Select the required profile.
3. Run Dependency/Readiness and Dry Run.
4. Confirm exact CPU/GPU target, backend, ISA, requested/resolved memory, and no blocking issues.
5. Start the profile only after those checks match this plan.
6. Stop the machine's remaining matrix after any verification mismatch, worker/device loss, uncontrolled OOM, runtime-guard stage abort, thermal shutdown, kernel GPU reset/fault, or unexpected backend/device substitution.

Heatsoak is a run-setup control rather than a JSON profile field. The final combined stages already provide logged 600-second full-pressure evidence. If an unlogged pre-test heatsoak is later required, use 10 minutes in Run Setup with architecture-neutral CPU Auto; do not count it as a substitute for a logged combined stage.

## Result handoff

Return the entire `results/<timestamp>_<profile-name>/` directory for each run. At minimum it must retain:

- `run_manifest.json`
- `profile_used.json`
- `run_metadata.json`
- `system_info.json`
- `raw_telemetry.csv`
- `telemetry_source_map.json`
- `parsed_results_extended.json`
- `parsed_results_custom.json`
- `run_summary.txt`
- complete `worker_results/`
- complete `worker_logs/`

Review requested versus selected backends, resolved CPU kernels and target IDs, affinity evidence, assigned/achieved RAM and GPU allocation, runtime-memory-guard evidence, GPU readback verification, CPU canaries, telemetry provenance, stage verdicts, and overall verdict.

## Deliberate omissions

- Native Auto is not another 600-second stage because it resolves to a family already sustained-tested; targeting profiles prove selection.
- No ARM x86-ISA, SVE, SVE2, SME, or OpenCL stages are created.
- Exact internal x86 FMA/integer kernel flavors are not profile vocabulary and are not exposed here.
- AVX512 and optional graphics APIs are isolated so one unavailable capability does not block otherwise valid profiles.
- External glmark2, vkmark, vkcube, and glxgears are omitted because they do not add controlled verification coverage.
- CPU backends are not multiplied across every GPU combination; combined profiles use native Auto/common-safe CPU execution.
- No profile deliberately forces runtime-memory-guard emergency behavior, OOM, device loss, or thermal shutdown.
