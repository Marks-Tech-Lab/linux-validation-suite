"""Bounded host-side OpenCL allocation diagnostics; no I/O or GPU queries."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import time


class OpenCLAllocationTiming:
    OPERATIONS = frozenset({"create_buffer", "allocation_touch_enqueue", "allocation_touch_finish",
                            "recurring_fill_enqueue", "recurring_fill_finish", "blocking_readback",
                            "readback_enqueue", "readback_batch_finish", "readback_event_status", "readback_recovery_finish",
                            "result_persistence", "sleep_yield"})

    def __init__(self, identity: dict, *, monotonic=time.monotonic, wall=time.time, cpu=time.process_time):
        self.monotonic, self.wall, self.cpu = monotonic, wall, cpu
        self.started, self.wall_started = monotonic(), wall()
        self.identity = dict(identity)
        self.operations = {}
        self.slow = deque(maxlen=32)
        self.slow_count = 0
        self.loops = 0
        self.attempts = self.interrupted = 0
        self.completed_elapsed = self.interrupted_elapsed = 0.0
        self.loop_elapsed = self.loop_unaccounted = self.loop_max = 0.0
        self.active_loop = None

    def _known(self):
        return sum(row["elapsed_seconds"] for row in self.operations.values())

    def begin_loop(self):
        if self.active_loop is not None:
            self.finish_loop()
        self.attempts += 1
        self.active_loop = (self.monotonic(), self._known())

    def finish_loop(self, *, completed=False):
        if self.active_loop is None:
            return
        start, known = self.active_loop
        elapsed = max(0.0, self.monotonic() - start)
        if completed:
            self.loops += 1
            self.completed_elapsed += elapsed
        else:
            self.interrupted += 1
            self.interrupted_elapsed += elapsed
        self.loop_elapsed += elapsed
        self.loop_max = max(self.loop_max, elapsed)
        self.loop_unaccounted += max(0.0, elapsed - (self._known() - known))
        self.active_loop = None

    @contextmanager
    def measure(self, operation):
        if operation not in self.OPERATIONS:
            raise ValueError("unrecognized OpenCL timing operation")
        start, cpu_start = self.monotonic(), self.cpu()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            end = self.monotonic()
            elapsed, cpu_elapsed = max(0.0, end - start), max(0.0, self.cpu() - cpu_start)
            row = self.operations.setdefault(operation, dict(count=0, elapsed_seconds=0.0,
                process_cpu_seconds=0.0, maximum_seconds=0.0, error_count=0))
            row["count"] += 1
            row["elapsed_seconds"] += elapsed
            row["process_cpu_seconds"] += cpu_elapsed
            row["error_count"] += int(failed)
            if elapsed >= row["maximum_seconds"]:
                row.update(maximum_seconds=elapsed, maximum_start_monotonic=start,
                           maximum_end_monotonic=end,
                           maximum_start_unix_seconds=self.wall_started + start - self.started)
            if elapsed >= .25:
                self.slow_count += 1
                self.slow.append(dict(operation=operation, start_monotonic=start, end_monotonic=end,
                    start_unix_seconds=self.wall_started + start - self.started,
                    elapsed_seconds=elapsed, process_cpu_seconds=cpu_elapsed, raised=failed))

    def call(self, operation, function, *args):
        with self.measure(operation):
            return function(*args)

    def snapshot(self):
        return dict(contract="opencl_allocation_timing_v1", identity=dict(self.identity),
            clock="monotonic", correlation_monotonic=self.started, correlation_unix_seconds=self.wall_started,
            observed_elapsed_seconds=max(0.0, self.monotonic() - self.started),
            operations={key: dict(value) for key, value in self.operations.items()},
            attempted_loop_count=self.attempts,
            completed_loop_count=self.loops, completed_loop_seconds=self.completed_elapsed,
            interrupted_loop_count=self.interrupted, interrupted_loop_seconds=self.interrupted_elapsed,
            observed_loop_seconds=self.loop_elapsed,
            maximum_loop_seconds=self.loop_max, unaccounted_loop_seconds=self.loop_unaccounted,
            loop_in_progress=self.active_loop is not None,
            slow_threshold_seconds=.25, slow_event_count=self.slow_count,
            slow_events_overwritten=max(0, self.slow_count - len(self.slow)), slow_events=list(self.slow),
            interpretation="host wall time; unaccounted includes Python work/scheduling, not an attributed cause",
            persistence_observation="a write includes prior completed writes; terminal stderr includes the last write")
