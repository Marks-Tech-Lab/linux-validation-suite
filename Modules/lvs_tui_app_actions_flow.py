#!/usr/bin/env python3
"""Shared list-state helpers for top-level TUI app actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from typing import Any, Callable, Sequence, Tuple


@dataclass(frozen=True)
class TuiSidebarListState:
    title: str
    rows: Tuple[str, ...]
    selected_index: int | None
    first_item: Any | None = None
    empty_detail: str = ""


@dataclass(frozen=True)
class GlobalActionCell:
    button_id: str
    hotkey: str
    label: str
    keypress: str
    start: int
    end: int


ACTION_BUTTONS: Tuple[Tuple[str, str], ...] = (
    ("profiles", "Profiles"),
    ("dry-run", "Dry"),
    ("deps", "Deps"),
    ("new-profile", "New"),
    ("setup", "Setup"),
    ("edit-profile", "Edit"),
    ("history", "History"),
    ("run", "Run"),
    ("results", "Results"),
    ("settings", "Settings"),
    ("migration-support", "Migration"),
    ("refresh", "Refresh"),
)


ACTION_BUTTON_ROWS: Tuple[Tuple[Tuple[str, str], ...], ...] = (
    (
        ("profiles", "Profiles"),
        ("dry-run", "Dry"),
        ("deps", "Deps"),
        ("new-profile", "New"),
        ("setup", "Setup"),
        ("edit-profile", "Edit"),
    ),
    (
        ("history", "History"),
        ("run", "Run"),
        ("results", "Results"),
        ("settings", "Settings"),
        ("migration-support", "Migration"),
        ("refresh", "Refresh"),
    ),
)


GLOBAL_ACTION_BUTTONS: Tuple[Tuple[str, str], ...] = (
    ("global-profiles", "P Profiles"),
    ("global-results", "S Results"),
    ("global-setup", "T Setup"),
    ("global-dry-run", "D Dry Run"),
    ("global-deps", "C Deps"),
    ("global-new-profile", "N New"),
    ("global-edit-profile", "M Edit"),
    ("global-run", "U Run"),
    ("global-upload", "G Upload"),
    ("global-wall-wattage", "W Watts"),
    ("global-settings", "X Settings"),
    ("global-refresh", "R Refresh"),
    ("global-back", "Esc Back"),
    ("global-quit", "Q Quit"),
)


GLOBAL_ACTION_BAR_ROWS: Tuple[Tuple[Tuple[str, str], ...], ...] = (
    (
        ("P", "Profiles"),
        ("S", "Results"),
        ("T", "Setup"),
        ("D", "Dry Run"),
        ("C", "Deps"),
        ("N", "New"),
        ("M", "Edit"),
    ),
    (
        ("U", "Run"),
        ("G", "Upload"),
        ("W", "Watts"),
        ("X", "Settings"),
        ("R", "Refresh"),
        ("Esc", "Back"),
        ("Q", "Quit"),
    ),
)


def layout_action_button_rows(
    buttons: Sequence[Tuple[str, str]],
    *,
    available_width: int | None = None,
    preferred_rows: int = 2,
) -> Tuple[Tuple[Tuple[str, str], ...], ...]:
    items = tuple((str(button_id), str(label)) for button_id, label in buttons)
    if not items:
        return tuple()
    if available_width is None or available_width <= 0:
        chunk_size = max(1, (len(items) + max(1, preferred_rows) - 1) // max(1, preferred_rows))
        return tuple(tuple(items[index : index + chunk_size]) for index in range(0, len(items), chunk_size))
    row_limit = max(24, int(available_width) - 4)
    rows: list[list[Tuple[str, str]]] = [[]]
    row_width = 0
    for item in items:
        _button_id, label = item
        item_width = max(8, len(label) + 4)
        separator_width = 1 if rows[-1] else 0
        if rows[-1] and row_width + separator_width + item_width > row_limit:
            rows.append([])
            row_width = 0
            separator_width = 0
        rows[-1].append(item)
        row_width += separator_width + item_width
    return tuple(tuple(row) for row in rows)


def split_global_action_label(label: object) -> tuple[str, str]:
    hotkey, sep, text = str(label or "").partition(" ")
    return hotkey, text if sep else ""


def global_action_keypress(label: object) -> str:
    hotkey, _text = split_global_action_label(label)
    value = hotkey.strip().lower()
    return "escape" if value == "esc" else value


def global_action_cell_rows(
    buttons: Sequence[Tuple[str, str]],
    *,
    available_width: int | None = None,
) -> Tuple[Tuple[GlobalActionCell, ...], ...]:
    width = int(available_width or 0)
    row_limit = max(24, width - 2) if width > 0 else 96
    rows: list[list[GlobalActionCell]] = [[]]
    cursor = 0
    for button_id, label in tuple((str(button_id), str(label)) for button_id, label in buttons):
        hotkey, text = split_global_action_label(label)
        plain = f"{hotkey} {text}".strip()
        prefix_width = 3 if rows[-1] else 0
        item_width = len(plain)
        if rows[-1] and cursor + prefix_width + item_width > row_limit:
            rows.append([])
            cursor = 0
            prefix_width = 0
        start = cursor + prefix_width
        end = start + item_width
        rows[-1].append(
            GlobalActionCell(
                button_id=button_id,
                hotkey=hotkey,
                label=text,
                keypress=global_action_keypress(label),
                start=start,
                end=end,
            )
        )
        cursor = end
    return tuple(tuple(row) for row in rows)


def action_layout_width(
    *,
    container_width: object = None,
    app_width: object = None,
    cached_width: object = None,
) -> int | None:
    for value in (container_width, app_width, cached_width):
        if isinstance(value, int) and value > 0:
            return value
    return None


def profiles_sidebar_state(
    profiles: Sequence[Any],
    *,
    environment_label: str,
    row_label: Callable[[Any], str],
) -> TuiSidebarListState:
    return TuiSidebarListState(
        title=f"Profiles | {environment_label}",
        rows=tuple(row_label(profile) for profile in profiles),
        selected_index=0 if profiles else None,
        first_item=profiles[0] if profiles else None,
        empty_detail="No profiles found.",
    )


def results_sidebar_state(
    results: Sequence[Any],
    *,
    row_label: Callable[[Any], str],
    selected_path: Any = None,
) -> TuiSidebarListState:
    selected_index = 0 if results else None
    selected_item = results[0] if results else None
    if selected_path is not None:
        target = Path(str(selected_path))
        for index, result in enumerate(results):
            if Path(str(getattr(result, "path", ""))) == target:
                selected_index = index
                selected_item = result
                break
    return TuiSidebarListState(
        title="Results",
        rows=tuple(row_label(result) for result in results),
        selected_index=selected_index,
        first_item=selected_item,
        empty_detail="No active result folders found.",
    )


def settings_sidebar_state() -> TuiSidebarListState:
    return TuiSidebarListState(
        title="Settings",
        rows=("Settings summary",),
        selected_index=0,
    )


def migration_support_sidebar_state() -> TuiSidebarListState:
    return TuiSidebarListState(
        title="Migration / Support",
        rows=(
            "Public-safe Support Summary",
            "Create Private Migration Bundle",
            "Preview Migration Restore",
            "Apply Reviewed Migration Restore",
        ),
        selected_index=0,
    )


def _wrap_help_text(prefix: str, body: str, width: int | None) -> str:
    if width is None or width >= 100:
        return f"{prefix}: {body}"
    usable_width = max(38, min(88, int(width) - 6))
    wrapped = wrap(
        f"{prefix}: {body}",
        width=usable_width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "\n".join(wrapped[:3])


def compact_action_help_text(view_mode: str, *, terminal_width: int | None = None) -> str:
    mode = str(view_mode or "").lower()
    if mode in {"results", "comparison_select"}:
        return _wrap_help_text(
            "Results keys",
            "Enter summary | E QA | V validation | M pre-import | O compare | F artifacts | D stages | I inventory | P profiles",
            terminal_width,
        )
    elif mode in {"setup", "confirm_run"}:
        return _wrap_help_text(
            "Setup keys",
            "Enter edit/action | U review/run | Esc/B back | H history | O stages | L labels | D debug",
            terminal_width,
        )
    elif mode == "settings":
        return _wrap_help_text(
            "Settings keys",
            "Enter toggle/edit | G upload prompt | W wall watts | R raw telemetry | P profiles",
            terminal_width,
        )
    elif mode == "migration_support":
        return _wrap_help_text(
            "Migration keys",
            "Enter select | private export requires PRIVATE | restore apply requires preview then APPLY",
            terminal_width,
        )
    elif mode.startswith("profile_edit"):
        return _wrap_help_text(
            "Profile edit keys",
            "Enter edit | S save | Esc/B back | D duplicate | Delete remove stage",
            terminal_width,
        )
    elif mode == "run_active":
        return _wrap_help_text(
            "Run keys",
            "monitor progress here | Esc shows cancel unavailable | wait for post-run actions",
            terminal_width,
        )
    return _wrap_help_text(
        "Main keys",
        "Enter setup/review | D dry run | K migration/support | S results | X settings | R refresh | Q quit",
        terminal_width,
    )


def global_action_bar_text(*, terminal_width: int | None = None) -> str:
    return "\n".join(
        " | ".join(f"{key} {label}" for key, label in row)
        for row in GLOBAL_ACTION_BAR_ROWS
    )


def global_action_markup(label: str) -> str:
    key, sep, text = str(label or "").partition(" ")
    if not sep:
        return f"[bold $accent]{key}[/]"
    return f"[bold $accent]{key}[/] [white]{text}[/]"
