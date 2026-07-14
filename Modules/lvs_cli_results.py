from __future__ import annotations

"""CLI adapter for result/report workflows."""

from typing import Any

from .lvs_cli_result_batch import ResultCliBatchMixin
from .lvs_cli_result_inventory import ResultCliInventoryMixin
from .lvs_cli_result_prompts import ResultCliPromptMixin
from .lvs_cli_result_selected import ResultCliSelectedMixin


class ResultCliAdapter(
    ResultCliInventoryMixin,
    ResultCliBatchMixin,
    ResultCliSelectedMixin,
    ResultCliPromptMixin,
):
    def __init__(self, launcher: Any) -> None:
        self.launcher = launcher

    def __getattr__(self, name: str) -> Any:
        return getattr(self.launcher, name)


class ResultsCompatibilityMixin:
    """Compatibility delegates for legacy launcher result helper methods."""

    def _results_cli_adapter(self) -> ResultCliAdapter:
        adapter = getattr(self, "results_cli", None)
        if adapter is None:
            adapter = ResultCliAdapter(self)
            self.results_cli = adapter
        return adapter

    def _results_menu(self) -> None:
        self._results_cli_adapter().results_menu()
