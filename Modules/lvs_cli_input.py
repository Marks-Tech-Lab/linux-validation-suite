from __future__ import annotations

import builtins
import select
import sys
import termios
import tty
from typing import List

from Modules.lvs_cli_compat import BackRequested


class TerminalInputAdapter:
    """Terminal input handling for CLI prompts and Back/Esc semantics."""

    def input(self, prompt: str, *, allow_back: bool = True) -> str:
        value = self.interactive_input(prompt) if sys.stdin.isatty() else builtins.input(prompt)
        if allow_back and self.is_back_input(value):
            raise BackRequested()
        return value

    def interactive_input(self, prompt: str) -> str:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        buffer: List[str] = []
        try:
            tty.setcbreak(fd)
            while True:
                char = sys.stdin.read(1)
                if char == "":
                    raise EOFError
                if char == "\x03":
                    raise KeyboardInterrupt
                if char == "\x04":
                    raise EOFError
                if char == "\x1b":
                    sequence = self.read_pending_escape_sequence()
                    if sequence:
                        continue
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    raise BackRequested()
                if char in {"\r", "\n"}:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(buffer)
                if char in {"\x7f", "\b"}:
                    if buffer:
                        buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if char.isprintable() or char == "\t":
                    buffer.append(char)
                    sys.stdout.write(char)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)

    def read_pending_escape_sequence(self) -> str:
        sequence = ""
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.01)
            if not ready:
                return sequence
            char = sys.stdin.read(1)
            if char == "":
                return sequence
            sequence += char
            if char.isalpha() or char == "~":
                return sequence

    def is_back_input(self, value: str) -> bool:
        text = str(value or "")
        normalized = text.strip().lower()
        return text == "\x1b" or normalized in {"esc", "escape", "back"}


class InputCompatibilityMixin:
    """Compatibility delegates for legacy launcher input helper methods."""

    def _input_cli_adapter(self) -> TerminalInputAdapter:
        adapter = getattr(self, "input_cli", None)
        if adapter is None:
            adapter = TerminalInputAdapter()
            self.input_cli = adapter
        return adapter

    def _input(self, prompt: str, *, allow_back: bool = True) -> str:
        return self._input_cli_adapter().input(prompt, allow_back=allow_back)

    def _interactive_input(self, prompt: str) -> str:
        return self._input_cli_adapter().interactive_input(prompt)

    def _read_pending_escape_sequence(self) -> str:
        return self._input_cli_adapter().read_pending_escape_sequence()

    def _is_back_input(self, value: str) -> bool:
        return self._input_cli_adapter().is_back_input(value)
