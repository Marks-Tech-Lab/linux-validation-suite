# Opt-in NVIDIA Vulkan startup bounds diagnostic

Use the current complete LVS working build on the Ryzen/RTX test system.
Do not run PL Validation or another GPU workload concurrently with this probe.
From that project's root, run:

```bash
.venv/bin/python -B native/vulkan_bounds_diagnostic.py --run \
  --target-slot 0000:01:00.0 \
  --target-device-uuid GPU-d5d67b06-3c02-6d92-ca68-fcb064c3bac7
```

These identifiers come from the captured RTX 5090 inventory. The command
requires both an independently known UUID and exact PCI identity. NVIDIA-only
selection uses the normal fail-closed native selector; names and ordinals are
not authorization. Do not reuse this command for a different GPU identity.

The probe allocates one nominal 3 GiB buffer and a 16 KiB independent output
buffer. The same large allocation is bound with 3 GiB and 1 GiB descriptor
ranges, both at offset zero. It conservatively charges 3 GiB + 1 MiB against
the existing system-memory reserve/guard policy, including device memory; this
charge is safety accounting, not a claim of actual physical host commitment.
Insufficient headroom or unsupported descriptor capacity stops the diagnostic.

Only the first workgroup's input words are initialized. Exactly one legal
workgroup executes; there is no ramp or stress loop. The shader instruments the
production indexing, two-word push-constant ABI and seven-round
stateful recurrence, with the former OpArrayLength guard deliberately restored
to reproduce the driver query. The second push word is the host descriptor
capacity; production uses it instead of the query. Independent output is written before the production
guard, using a separate fixed bound. Shader-observed values and decisions are
recorded for every invocation, including word 1. Data word 1 is separately
copied back after compute completion. The logical push value is the recorded
281,858,304 words; the actual diagnostic grid is 1×1×1, not the historical
1,101,009×1×1 grid. This isolates the word-1 bounds question with minimal work.

The supervisor enforces a 30-second deadline, cancellation and the normal
runtime MemAvailable guard. Termination allows five seconds for cleanup before
forced kill. A timeout, abnormal exit, invalid output marker or cleanup error
is incomplete/error evidence, never a successful stress validation.

The command prints a newly created `results/<timestamp>_Vulkan_Bounds_Startup_*`
directory. Return the entire directory: `diagnostic_manifest.json`,
`diagnostic_result.json`, `runtime_memory_guard.json`, `stdout.log` and
`stderr.log`. Source provenance is automatic. The result records shader hash,
expected/observed values, identity and cleanup; no executable is attached.
`status=observed` / exit zero means observations were collected, NOT that the
production compute workload passed. This directory is deliberately distinct
from normal profile execution and does not fabricate a profile/worker PASS.

Interpretation:

- Correct push value, large length zero/incorrect, small length 268,435,456:
  large-descriptor array-length discrepancy, consistent with the documented
  NVIDIA issue. Expected large length is 805,306,368. Inspect word-1 guards too.
- Incorrect shader-observed push value: push-constant delivery/ABI discrepancy;
  it explains the skipped write only if the observed guard excludes word 1.
- Correct bounds but data word 1 differs from 1,003,605,230: execution,
  descriptor access or visibility remains unresolved.
- Correct observations and word 1: this minimal probe did not reproduce the
  production failure; it does not clear the larger dispatch/concurrency case.
- Missing/inconsistent independent output: do not infer either query or push
  behavior from zeros. Preserve logs and investigate the diagnostic failure.

The October 26 RTX 5090 capture observed the correct logical push value,
zero large-view length, correct small-view length, valid independent markers,
and a rejected large-view word-1 guard. Production now uses two host-validated
push words: logical work and exact descriptor capacity. Both guards remain;
allocation sizes and verification are unchanged. The diagnostic intentionally
retains the query to permit direct investigation of this driver behavior.
Subsequent physical validation on the RTX 5090 and RTX PRO 6000 Blackwell
workstation configurations successfully exercised large dedicated-VRAM Vulkan
allocations with the corrected descriptor-capacity handling. Sampled computation
completed with zero mismatches, confirmed cleanup and finalized successful
results. This closes the large-descriptor bounds acceptance issue for those
tested configurations; it does not establish universal NVIDIA hardware acceptance
or exhaustive memory verification. The diagnostic retains the original query
mechanism and its coverage limitations for future investigation.

Reference: [Dawn's documented NVIDIA large-buffer OpArrayLength issue](https://dawn.googlesource.com/dawn/+/4d0ebb4a8ef52203223e97bc15880e7fb0f733c5%5E%21/).
