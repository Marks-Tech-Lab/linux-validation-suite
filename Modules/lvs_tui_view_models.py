from __future__ import annotations

from typing import Any, Iterable, List, Tuple


def profile_row_label(profile: Any) -> str:
    return f"{profile.name}\n  {profile.menu_group_label}"


def result_row_label(result: Any) -> str:
    return f"{result.name}\n  {result.verdict}"


def setup_history_row_label(entry: Any) -> str:
    return (
        f"{entry.case_sku} | {entry.description}\n"
        f"  {entry.profile_name or entry.profile_file} | {entry.psu_wattage} | {entry.saved}"
    )


def profile_edit_row_label(item: Any) -> str:
    return str(item.label)


def setup_action_row_label(action: Any) -> str:
    key = str(action.key or "").upper()
    label = str(action.label or action.target or action.action or key)
    detail = str(getattr(action, "detail", "") or "").strip()
    suffix = f" -- {detail}" if detail else ""
    return f"{label}\n{key}{suffix}"


def picker_row_labels(options: Iterable[str], current: str = "") -> Tuple[List[str], int]:
    labels: List[str] = []
    selected_index = 0
    current_lower = str(current or "").strip().lower()
    for option_index, option in enumerate(options):
        marker = " <- current" if current_lower and str(option).lower() == current_lower else ""
        if marker:
            selected_index = option_index
        labels.append(f"{option}{marker}")
    return labels, selected_index
