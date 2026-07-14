from __future__ import annotations

from typing import Any, Callable, Iterable, Optional


async def replace_list_labels(
    list_view: Any,
    labels: Iterable[str],
    item_factory: Callable[[str], Any],
    *,
    selected_index: Optional[int] = None,
    focus: bool = False,
) -> int:
    rows = list(labels)
    await list_view.clear()
    for label in rows:
        await list_view.append(item_factory(label))
    if rows and selected_index is not None:
        list_view.index = min(max(0, int(selected_index)), len(rows) - 1)
    if focus:
        list_view.focus()
    return len(rows)
