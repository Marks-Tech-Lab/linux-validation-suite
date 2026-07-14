from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from Modules.lvs_diagnostics_cli import DiagnosticsCliAdapter
from Modules.lvs_profile_models import ValidationProfile


class DiagnosticsCompatibilityMixin:
    """Compatibility delegates for legacy launcher diagnostics helper methods."""

    def _diagnostics_cli_adapter(self) -> DiagnosticsCliAdapter:
        adapter = getattr(self, "diagnostics_cli", None)
        if adapter is None:
            adapter = DiagnosticsCliAdapter(self)
            self.diagnostics_cli = adapter
        return adapter

    def _diagnostics_menu(self) -> None:
        self._diagnostics_cli_adapter().diagnostics_menu()

    def _dry_run_diagnostics(self) -> None:
        self._diagnostics_cli_adapter().dry_run_diagnostics()

    def _write_diagnostics_report(
        self,
        profile_path: Path,
        profile: ValidationProfile,
        labels: List[str],
        report: Dict[str, Any],
    ) -> Path:
        return self._diagnostics_cli_adapter().write_diagnostics_report(profile_path, profile, labels, report)

    def _diagnostics_summary_text(self, report: Dict[str, Any]) -> str:
        return self._diagnostics_cli_adapter().diagnostics_summary_text(report)

    def _preflight_summary_text(self, report: Dict[str, Any]) -> str:
        return self.profile_reports.preflight_summary_text(report)

    def _print_diagnostics_summary(self, report: Dict[str, Any]) -> None:
        self._diagnostics_cli_adapter().print_diagnostics_summary(report)

    def _memory_module_has_identity(self, module: Dict[str, Any]) -> bool:
        return self._diagnostics_cli_adapter().memory_module_has_identity(module)

    def _dependency_check(self) -> None:
        self._diagnostics_cli_adapter().dependency_check()

    def _dependency_check_summary_text(self, payload: Dict[str, Any], report_dir: Optional[Path] = None) -> str:
        return self._diagnostics_cli_adapter().dependency_check_summary_text(payload, report_dir)
