"""One terminal byte owner for prompts and bounded live workload controls.

Independent open descriptions keep O_NONBLOCK off the caller's stdin/stdout.
No terminal modes are changed. Complete commands remain queued across polls;
oversized input fails closed instead of interpreting a truncated suffix.
"""
from collections import deque
import errno
import os
import select
import stat
import termios


class TerminalInput:
    MAX_LINE = 512
    MAX_QUEUE = 32
    READ_BUDGET = 4096
    COMMAND_BUDGET = 16
    OUTPUT_LIMIT = 8192
    MARKERS = (b'\x1b[200~', b'\x1b[201~')

    def __init__(self, stdin, stdout):
        self.fd = self.output_fd = None
        self.original_fd = stdin.fileno()
        self.settings = termios.tcgetattr(self.original_fd)
        self.lines = deque()
        self.line = bytearray()
        self.escape = bytearray()
        self.output = bytearray()
        self.last_cr = False
        self.failure = None
        self.eof = False
        self.stop_notified = False
        self.stats = dict(bytes_read=0, overflow=False, dropped_display_bytes=0,
                          max_queued_commands=0, max_line_bytes=0)
        try:
            self.fd = self._open(self.original_fd, os.O_RDONLY)
            if stdout.isatty():
                self.output_fd = self._open(stdout.fileno(), os.O_WRONLY)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _open(fd, access):
        before = os.fstat(fd)
        result = os.open(f'/proc/self/fd/{fd}', access | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY)
        after = os.fstat(result)
        if (not stat.S_ISCHR(after.st_mode) or not os.isatty(result)
                or (before.st_dev, before.st_ino, before.st_rdev) != (after.st_dev, after.st_ino, after.st_rdev)):
            os.close(result)
            raise ValueError('terminal identity changed')
        return result

    def close(self):
        # Also restores settings if a caller changed them during an exception.
        try:
            if termios.tcgetattr(self.original_fd) != self.settings:
                termios.tcsetattr(self.original_fd, termios.TCSANOW, self.settings)
        finally:
            for name in ('fd', 'output_fd'):
                fd = getattr(self, name, None)
                if fd is not None:
                    os.close(fd)
                    setattr(self, name, None)

    def _fail(self, reason):
        self.failure = self.failure or reason
        self.stats['overflow'] |= reason == 'input capacity exceeded'
        self.line.clear()
        self.escape.clear()
        self.lines.clear()

    def _byte(self, value):
        if value in (10, 13):
            if value == 10 and self.last_cr:
                self.last_cr = False
                return
            self.last_cr = value == 13
            if len(self.lines) >= self.MAX_QUEUE:
                self._fail('input capacity exceeded')
                return
            self.lines.append(bytes(self.line))
            self.line.clear()
            self.stats['max_queued_commands'] = max(self.stats['max_queued_commands'], len(self.lines))
        else:
            self.last_cr = False
            if len(self.line) >= self.MAX_LINE:
                self._fail('input capacity exceeded')
                return
            self.line.append(value)
            self.stats['max_line_bytes'] = max(self.stats['max_line_bytes'], len(self.line))

    def _feed(self, data):
        for value in data:
            if self.failure:
                break
            if value == 3:
                # Raw/noncanonical terminals may deliver Ctrl+C as a byte
                # instead of generating SIGINT. It is an immediate stop request.
                self.line.clear();self.escape.clear()
                if len(self.lines)>=self.MAX_QUEUE:self._fail('input capacity exceeded')
                else:
                    self.lines.append(b'\x03')
                    self.stats['max_queued_commands']=max(self.stats['max_queued_commands'],len(self.lines))
            elif self.escape or value == 27:
                self.escape.append(value)
                candidate = bytes(self.escape)
                if candidate in self.MARKERS:
                    self.escape.clear()
                elif not any(marker.startswith(candidate) for marker in self.MARKERS):
                    pending = bytes(self.escape)
                    self.escape.clear()
                    for byte in pending:
                        self._byte(byte)
            else:
                self._byte(value)

    def read(self):
        remaining = self.READ_BUDGET
        while remaining and not self.failure and not self.eof:
            try:
                if not select.select([self.fd],[],[],0)[0]:break
                data = os.read(self.fd, min(1024, remaining))
            except BlockingIOError:
                break
            except InterruptedError:
                # Leave further work for the next safety polling cycle.
                break
            except OSError as error:
                self._fail(f'terminal read failed: {error.errno}')
                break
            if not data:
                self.eof = True
                break
            self.stats['bytes_read'] += len(data)
            remaining -= len(data)
            self._feed(data)

    def poll(self):
        self.read()
        result = []
        for _ in range(self.COMMAND_BUDGET):
            if not self.lines:
                break
            raw = self.lines.popleft()
            try:
                result.append(raw.decode('utf-8', errors='strict'))
            except UnicodeDecodeError:
                result.append('\ufffd')
        return result

    def write(self, text=''):
        data = (str(text) + '\n').encode('utf-8', errors='replace')
        room = self.OUTPUT_LIMIT - len(self.output)
        self.output.extend(data[:room])
        self.stats['dropped_display_bytes'] += max(0, len(data) - room)
        self.flush()

    def flush(self):
        if not self.output:
            return
        if self.output_fd is None:
            self.stats['dropped_display_bytes'] += len(self.output)
            self.output.clear()
            return
        try:
            count = os.write(self.output_fd, self.output)
            del self.output[:count]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as error:
            if error.errno not in (errno.EAGAIN, errno.EINTR):
                self.stats['dropped_display_bytes'] += len(self.output)
                self.output.clear()

    def ask(self, prompt=''):
        self.write(prompt)
        while True:
            self.flush()
            if self.lines:
                return self.lines.popleft().decode('utf-8', errors='replace')
            if self.failure or self.eof:
                raise EOFError(self.failure or 'terminal closed')
            select.select([self.fd], [], [], .1)
            self.read()

    def finish_activity(self):
        # Live controls cannot become confirmation/menu choices after a run.
        self.line.clear();self.escape.clear();self.lines.clear();self.last_cr=False
        termios.tcflush(self.original_fd,termios.TCIFLUSH)
        self.flush()

    def snapshot(self):
        return dict(self.stats, failure=self.failure, eof=self.eof,
                    pending_commands=len(self.lines), pending_bytes=len(self.line) + len(self.escape),
                    pending_display_bytes=len(self.output))
