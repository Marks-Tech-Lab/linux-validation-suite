"""Textual-free input activation state for the optional TUI frontend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_SETUP_INPUT_PLACEHOLDER = "Setup input appears here when editing a field."


@dataclass(frozen=True)
class TuiInputState:
    pending_field: str
    value: str = ""
    placeholder: str = ""
    detail: str = ""
    blank_default: str = ""
    enabled: bool = True
    focus: bool = True


@dataclass(frozen=True)
class TuiInputResetState:
    value: str = ""
    placeholder: str = DEFAULT_SETUP_INPUT_PLACEHOLDER
    blank_default: str = ""
    enabled: bool = False


def tui_input_state(
    pending_field: str,
    *,
    value: Any = "",
    placeholder: str = "",
    detail: str = "",
    blank_default: str = "",
    enabled: bool = True,
    focus: bool = True,
) -> TuiInputState:
    return TuiInputState(
        pending_field=str(pending_field),
        value="" if value is None else str(value),
        placeholder=str(placeholder),
        detail=str(detail),
        blank_default=str(blank_default),
        enabled=bool(enabled),
        focus=bool(focus),
    )


def tui_input_reset_state(
    *,
    value: Any = "",
    placeholder: str = DEFAULT_SETUP_INPUT_PLACEHOLDER,
    blank_default: str = "",
    enabled: bool = False,
) -> TuiInputResetState:
    return TuiInputResetState(
        value="" if value is None else str(value),
        placeholder=str(placeholder),
        blank_default=str(blank_default),
        enabled=bool(enabled),
    )
