"""Opt-in AMD dispatch timestamp observation; never a scheduler-job attestation."""
from __future__ import annotations

import ctypes
import json
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import threading
import time

from .lvs_runtime_memory_guard import _write_json_atomic
from .lvs_vulkan_identity import canonical_pci_slot

ENV = "LVS_AMD_VULKAN_DISPATCH_TIMING"
MAX_DISPATCHES = 64
MAX_RECORDS = 64
DEADLINE_SECONDS = 120.0
CLEANUP_SECONDS = 5.0


def timestamp_seconds(start, end, period_ns, valid_bits):
    if type(valid_bits) is not int or not 1 <= valid_bits <= 64:
        raise ValueError("invalid timestamp valid-bit count")
    if not math.isfinite(period_ns) or period_ns <= 0:
        raise ValueError("invalid timestamp period")
    mask = (1 << valid_bits) - 1
    return ((int(end) - int(start)) & mask) * period_ns / 1_000_000_000


def decode_cycle(ticks, dispatches, period_ns, valid_bits, host_seconds):
    if not 0 < len(dispatches) <= MAX_DISPATCHES or len(ticks) != 2 + 2*len(dispatches):
        raise ValueError("incomplete timestamp results")
    # A fence-bracketed host window must be shorter than the counter wrap;
    # otherwise modulo subtraction cannot establish elapsed GPU time.
    wrap = (1 << valid_bits) * period_ns / 1_000_000_000
    if not math.isfinite(host_seconds) or host_seconds < 0 or host_seconds >= wrap:
        raise ValueError("timestamp counter wrap cannot be disambiguated")
    seconds = timestamp_seconds(ticks[0], ticks[1], period_ns, valid_bits)
    if seconds > host_seconds + .001:
        raise ValueError("GPU timestamp interval exceeds host submission window")
    records = []
    for i, geometry in enumerate(dispatches):
        elapsed = timestamp_seconds(ticks[2+2*i], ticks[3+2*i], period_ns, valid_bits)
        if elapsed > seconds + .001:
            raise ValueError("dispatch timestamp interval exceeds submission interval")
        records.append({**geometry, "gpu_compute_stage_seconds": elapsed})
    return {"gpu_submission_seconds": seconds, "dispatches": records}


def read_kernel_cursor():
    """Require demonstrably readable current-boot kernel journal, not empty output."""
    result = subprocess.run(["journalctl", "-k", "-n", "1", "-o", "json", "--no-pager"],
                            capture_output=True, timeout=2, check=True)
    event = json.loads(result.stdout)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    if (event.get("_TRANSPORT") != "kernel" or event.get("_BOOT_ID") != boot
            or not event.get("__CURSOR")):
        raise RuntimeError("current-boot kernel journal evidence unavailable")
    return event["__CURSOR"]


class DispatchTimingDiagnostic:
    def __init__(self, state, result_file, slot):
        self.state = state
        self.slot = canonical_pci_slot(slot)
        if not self.slot or not result_file:
            raise RuntimeError("dispatch diagnostic requires exact PCI identity and result file")
        self.result_file = Path(result_file)
        self.stop_reason = ""
        self.stop_event = None
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.kernel = None
        self.thread = None
        self.kill_timer = None
        self.evidence = dict(contract_id="linux_validation_suite.vulkan_dispatch_timing", contract_version=1,
            diagnostic_only=True, status="starting", record_capacity=MAX_RECORDS, records=[], overwritten_records=0,
            timestamp_semantics="compute_stage_brackets_may_include_stalls_overlap_not_scheduler_job_boundaries",
            kernel_monitor_status="not_started", target_pci_slot=self.slot,
            deadline_seconds=DEADLINE_SECONDS, cleanup_grace_seconds=CLEANUP_SECONDS)
        state["dispatch_timing_evidence"] = self.evidence

    def start(self):
        cursor = read_kernel_cursor()
        self.kernel = subprocess.Popen(["journalctl", "-k", "-f", "--after-cursor", cursor,
                                       "-o", "json", "--no-pager"], stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL)
        os.set_blocking(self.kernel.stdout.fileno(), False)
        self.evidence.update(kernel_monitor_status="following_current_boot_cursor", status="enabled")
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def stop(self, reason, event=None):
        with self.lock:
            if self.stop_reason or self.finished.is_set():
                return
            self.stop_reason, self.stop_event = reason, event
            # Arm the hard bound before filesystem I/O or cleanup.
            self.kill_timer = threading.Timer(CLEANUP_SECONDS, self._hard_stop)
            self.kill_timer.daemon = True
            self.kill_timer.start()
        _write_json_atomic(Path(str(self.result_file) + ".diagnostic-stop.json"), {
            "status": "stopping", "reason": reason, "kernel_event": event,
            "worker_pid": os.getpid(), "target_pci_slot": self.slot,
            "cleanup_complete": None, "termination_after_seconds": CLEANUP_SECONDS})

    def _hard_stop(self):
        if not self.finished.is_set():
            # A wedged Vulkan call must not defeat the diagnostic deadline.
            # Retained external claims and missing terminal JSON stay unknown.
            try:
                if self.kernel:
                    # Do not orphan the journal follower when bypassing finally.
                    self.kernel.kill()
            finally:
                os._exit(124)

    def _monitor(self):
        try:
            buffer = b""
            with selectors.DefaultSelector() as selector:
                selector.register(self.kernel.stdout, selectors.EVENT_READ)
                while not self.finished.is_set():
                    if time.monotonic()-self.started >= DEADLINE_SECONDS:
                        self.stop("diagnostic_deadline"); return
                    if self.kernel.poll() is not None:
                        self.stop("kernel_monitor_exited"); return
                    if not selector.select(.05):
                        continue
                    data = os.read(self.kernel.stdout.fileno(), 65536)
                    if not data:
                        self.stop("kernel_monitor_eof"); return
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if len(line) > 65536:
                            raise ValueError("kernel journal record exceeds diagnostic bound")
                        event = json.loads(line)
                        if self.kernel_fault(event):
                            self.stop("amdgpu_kernel_fault", {k:event.get(k) for k in
                                ("MESSAGE", "__REALTIME_TIMESTAMP", "_BOOT_ID", "__CURSOR")}); return
                    if len(buffer) > 65536:
                        raise ValueError("unterminated kernel record exceeds diagnostic bound")
        except Exception as exc:
            self.stop("kernel_monitor_error:" + type(exc).__name__)

    def kernel_fault(self, event):
        text = str(event.get("MESSAGE") or "").lower()
        return (event.get("_TRANSPORT") == "kernel" and "amdgpu" in text
                and self.slot in text and bool(re.search(r"timeout|reset|fault|wedged", text)))

    def check(self):
        if self.stop_reason:
            self.evidence.update(status="stopped", stop_reason=self.stop_reason, kernel_event=self.stop_event)
            raise RuntimeError("Vulkan dispatch diagnostic stopped: " + self.stop_reason)

    def wait(self, vk, device, fences):
        started = time.monotonic()
        while True:
            self.check()
            code = int(vk.vkWaitForFences(device, 1, fences, 1, 50_000_000))
            if code == 0:
                self.check(); return 0
            if code != 2:  # VK_TIMEOUT is a polling result, not completed work.
                raise RuntimeError(f"vkWaitForFences diagnostic API error: {code}")
            if time.monotonic()-started >= 10:
                self.stop("fence_deadline")
                self.check()

    def record(self, cycle, ticks, dispatches, period_ns, valid_bits, host_seconds, fence_seconds):
        self.check()
        record = decode_cycle(ticks, dispatches, period_ns, valid_bits, host_seconds)
        record.update(cycle=cycle, fence_completed=True, host_submission_seconds=host_seconds,
                      host_fence_seconds=fence_seconds, recorded_unix_seconds=time.time(),
                      arithmetic_verification="separate_worker_verification_evidence")
        records = self.evidence["records"]
        if len(records) == MAX_RECORDS:
            del records[0]; self.evidence["overwritten_records"] += 1
        records.append(record)

    def close(self):
        with self.lock:
            self.finished.set()
            if self.kill_timer:
                self.kill_timer.cancel()
        if self.kernel:
            self.kernel.terminate()
            try: self.kernel.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                self.kernel.kill(); self.kernel.wait(timeout=.5)
            self.kernel.stdout.close()
        if self.thread:
            self.thread.join(timeout=.2)
