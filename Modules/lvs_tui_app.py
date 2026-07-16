from __future__ import annotations

"""Textual application shell for the optional Linux Validation Suite TUI."""

from pathlib import Path
import threading
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Header, Input, Label, ListItem, ListView, Static

from Modules.linux_validation_suite_service import SuiteAppService
from Modules.lvs_run_progress import RunStatusTracker
from Modules.lvs_service_models import (
    FrontendActionSpec,
    ProfileEditItem,
    ProfileEditState,
    ProfileListEntry,
    ResultListEntry,
    RunSetupHistoryEntry,
    RunSetupState,
)
from Modules.lvs_tui_app_actions_adapter import TuiAppActionsAdapterMixin
from Modules.lvs_tui_app_actions_flow import (
    ACTION_BUTTON_ROWS,
    GLOBAL_ACTION_BUTTONS,
    action_layout_width,
    compact_action_help_text,
    global_action_markup,
    layout_action_button_rows,
)
from Modules.lvs_tui_event_adapter import TuiEventAdapterMixin
from Modules.lvs_tui_input_state import TuiInputResetState, TuiInputState, tui_input_reset_state
from Modules.lvs_tui_list_adapter import replace_list_labels
from Modules.lvs_tui_navigation_state import TuiNavigationReset
from Modules.lvs_tui_profile_edit_adapter import TuiProfileEditAdapterMixin
from Modules.lvs_tui_results_adapter import TuiResultsAdapterMixin
from Modules.lvs_tui_run_execution_adapter import TuiRunExecutionAdapterMixin
from Modules.lvs_tui_run_presentation import live_system_layout, live_system_text
from Modules.lvs_tui_run_setup_adapter import TuiRunSetupAdapterMixin
from Modules.lvs_tui_settings_adapter import TuiSettingsAdapterMixin


class LinuxValidationSuiteTui(
    TuiAppActionsAdapterMixin,
    TuiEventAdapterMixin,
    TuiResultsAdapterMixin,
    TuiSettingsAdapterMixin,
    TuiProfileEditAdapterMixin,
    TuiRunSetupAdapterMixin,
    TuiRunExecutionAdapterMixin,
    App[None],
):
    CSS = """
    Screen {
        layout: vertical;
    }
    #body {
        height: 1fr;
        width: 100%;
    }
    #sidebar {
        width: 28%;
        min-width: 32;
        max-width: 64;
        border: solid $primary;
    }
    #main {
        width: 1fr;
        height: 1fr;
        border: solid $primary;
    }
    #run-detail-area {
        height: 1fr;
        width: 100%;
    }
    #detail {
        height: 1fr;
        width: 1fr;
        overflow: auto;
        padding: 1 3;
    }
    #live-system {
        display: none;
        height: 1fr;
        width: 32;
        min-width: 28;
        max-width: 36;
        overflow: auto;
        padding: 1 2;
        border-left: solid $primary;
    }
    #live-system.live-system-visible {
        display: block;
    }
    #actions {
        height: 7;
        width: 100%;
        padding: 0 1;
        border-top: solid $primary;
    }
    .action-row {
        height: 3;
        width: 100%;
    }
    #action-help {
        height: 3;
        max-height: 3;
        padding: 0 3;
        color: $text-muted;
    }
    #setup-input {
        height: 3;
        margin: 0 1;
    }
    #status {
        height: 3;
        padding: 0 2;
        color: $text-muted;
    }
    #global-actions {
        height: 4;
        width: 100%;
        padding: 0 0;
        border-top: solid $primary;
    }
    .global-action-row {
        height: 1;
        width: auto;
    }
    #actions Button {
        width: 1fr;
        min-width: 6;
        margin-right: 0;
    }
    #global-actions Button {
        width: auto;
        min-width: 1;
        height: 1;
        padding: 0 0;
        margin: 0 1 0 0;
        border: none;
        background: transparent;
        color: $text;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "cancel_setup_input", "Cancel"),
        ("r", "refresh", "Refresh"),
        ("d", "dry_run", "Dry Run"),
        ("c", "dependency_check", "Deps"),
        ("k", "show_migration_support", "Migration"),
        ("n", "new_profile", "New"),
        ("t", "setup_run", "Setup"),
        ("m", "edit_profile", "Edit"),
        ("h", "load_setup_history", "History"),
        ("u", "run_selected", "Run"),
        ("w", "edit_wall_wattage", "Wall W"),
        ("g", "upload_last_result", "Upload"),
        ("s", "show_results", "Results"),
        ("p", "show_profiles", "Profiles"),
        ("x", "show_settings", "Settings"),
    ]

    def __init__(self, service: SuiteAppService) -> None:
        super().__init__()
        self.service = service
        self.profiles: list[ProfileListEntry] = []
        self.results: list[ResultListEntry] = []
        self.selected_profile: Optional[ProfileListEntry] = None
        self.selected_result: Optional[ResultListEntry] = None
        self.comparison_target_result: Optional[ResultListEntry] = None
        self.profile_edit: Optional[ProfileEditState] = None
        self.profile_edit_items: list[ProfileEditItem] = []
        self.profile_edit_selected_index = 0
        self.profile_edit_picker_key: Optional[str] = None
        self.profile_edit_picker_options: list[str] = []
        self.profile_edit_picker_stage_index: Optional[int] = None
        self.profile_edit_discard_confirm = False
        self.view_mode = "profiles"
        self.confirm_run = False
        self.run_in_progress = False
        self.run_cancel_requested = False
        self.run_cancel_event = threading.Event()
        self.dry_run_in_progress = False
        self.upload_in_progress = False
        self.run_setup: Optional[RunSetupState] = None
        self.pending_input_field: Optional[str] = None
        self.pending_input_blank_default = ""
        self.setup_picker_key: Optional[str] = None
        self.setup_picker_options: list[str] = []
        self.setup_actions: list[FrontendActionSpec] = []
        self.power_limit_parts: dict[str, str] = {}
        self.pending_stage_index: Optional[int] = None
        self.pending_trim_start: Optional[int] = None
        self.setting_list_key: Optional[str] = None
        self.setting_list_selected_index: int = 0
        self.history_entries: list[RunSetupHistoryEntry] = []
        self.pending_history_entry: Optional[RunSetupHistoryEntry] = None
        self.pending_migration_bundle_path: Optional[Path] = None
        self.last_audit_notes: list[str] = []
        self.last_run_dir: Optional[Path] = None
        self.last_run_metadata = None
        self.run_live_lines: list[str] = []
        self.run_live_profile_name = ""
        self.run_live_phase_line = ""
        self.run_status_tracker = RunStatusTracker()
        self.status_message = "Ready"
        self.post_run_upload_prompt_text = ""
        self._last_global_action_width: Optional[int] = None
        self._rendered_global_action_width: Optional[int] = None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.run_in_progress:
            return True if action == "cancel_setup_input" else None
        if self.upload_in_progress:
            return True if action == "quit" else None
        if self.pending_input_field or self.setup_picker_key:
            return True if action == "cancel_setup_input" else None
        if action == "cancel_setup_input":
            return False
        return True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Horizontal(
            Vertical(
                Label("Profiles", id="sidebar-title"),
                ListView(id="items"),
                id="sidebar",
            ),
            Vertical(
                Horizontal(
                    Static("", id="detail"),
                    Static("", id="live-system"),
                    id="run-detail-area",
                ),
                Static("", id="action-help"),
                Vertical(
                    *(
                        Horizontal(
                            *(Button(label, id=button_id) for button_id, label in row),
                            classes="action-row",
                        )
                        for row in ACTION_BUTTON_ROWS
                    ),
                    id="actions",
                ),
                Input(
                    placeholder="Setup input appears here when editing a field.",
                    id="setup-input",
                    disabled=True,
                ),
                Static("Ready", id="status"),
                id="main",
            ),
            id="body",
        )
        yield Vertical(id="global-actions")

    async def on_mount(self) -> None:
        self._refresh_global_action_buttons()
        await self.action_show_profiles()
        self._refresh_global_action_buttons()
        call_after_refresh = getattr(self, "call_after_refresh", None)
        if callable(call_after_refresh):
            call_after_refresh(self._refresh_global_action_buttons)
        set_interval = getattr(self, "set_interval", None)
        if callable(set_interval):
            set_interval(0.25, self._refresh_global_action_buttons)

    def on_resize(self, event) -> None:  # pragma: no cover - exercised by Textual runtime
        size = getattr(event, "size", None)
        width = getattr(size, "width", None)
        if not isinstance(width, int) or width <= 0:
            width = getattr(event, "width", None)
        if isinstance(width, int) and width > 0:
            self._last_global_action_width = width
            self._rendered_global_action_width = None
        self._set_action_help()
        self._refresh_live_system_pane()
        self._refresh_global_action_buttons()

    async def on_unmount(self) -> None:
        self.service.stop_enhanced_telemetry_keepalive()

    async def _replace_sidebar_labels(
        self,
        list_view,
        labels: list[str],
        selected_index: Optional[int] = None,
        focus: bool = False,
    ) -> int:
        return await replace_list_labels(
            list_view,
            labels,
            lambda text: ListItem(Label(text)),
            selected_index=selected_index,
            focus=focus,
        )

    def _apply_input_state(self, state: TuiInputState) -> None:
        self.pending_input_field = state.pending_field
        self.pending_input_blank_default = state.blank_default
        self.confirm_run = False
        input_widget = self.query_one("#setup-input", Input)
        input_widget.disabled = not state.enabled
        input_widget.value = state.value
        input_widget.placeholder = state.placeholder
        if state.focus:
            input_widget.focus()
        if state.detail:
            self._set_detail(state.detail)

    def _apply_input_reset_state(self, state: TuiInputResetState) -> None:
        input_widget = self.query_one("#setup-input", Input)
        input_widget.value = state.value
        input_widget.placeholder = state.placeholder
        input_widget.disabled = not state.enabled
        self.pending_input_blank_default = state.blank_default

    def _apply_navigation_reset(self, reset: TuiNavigationReset) -> None:
        if reset.clear_confirm_run:
            self.confirm_run = False
        if reset.clear_pending_input:
            self.pending_input_field = None
        if reset.clear_setup_picker:
            self.setup_picker_key = None
            self.setup_picker_options = []
        if reset.clear_profile_edit_picker:
            self.profile_edit_picker_key = None
            self.profile_edit_picker_options = []
            self.profile_edit_picker_stage_index = None
        if reset.clear_setting_list:
            self.setting_list_key = None
        if reset.clear_selected_profile:
            self.selected_profile = None
        if reset.clear_selected_result:
            self.selected_result = None
            self.comparison_target_result = None
        if reset.reset_input_widget:
            self._reset_entry_input()

    def _set_detail(self, text: str) -> None:
        self.query_one("#detail", Static).update(text)
        self._refresh_live_system_pane()
        self._set_action_help()

    def _refresh_live_system_pane(self) -> None:
        try:
            widget = self.query_one("#live-system", Static)
            terminal_width = int(getattr(getattr(self, "size", None), "width", 0) or 0)
            layout = live_system_layout(
                terminal_width=terminal_width,
                run_active=bool(getattr(self, "run_in_progress", False))
                and str(getattr(self, "view_mode", "")) == "run_active",
            )
            widget.set_class(layout.visible, "live-system-visible")
            if layout.visible:
                tracker = getattr(self, "run_status_tracker", None)
                widget.update(live_system_text(getattr(tracker, "events", ())))
            else:
                widget.update("")
        except Exception:
            pass

    def _set_action_help(self) -> None:
        try:
            terminal_width = int(getattr(getattr(self, "size", None), "width", 0) or 0) or None
            width = max(36, terminal_width - 48) if terminal_width is not None else None
            self.query_one("#action-help", Static).update(
                compact_action_help_text(str(getattr(self, "view_mode", "")), terminal_width=width)
            )
        except Exception:
            pass

    def _global_button_row(self, row: tuple[tuple[str, str], ...]) -> Horizontal:
        controls = []
        for index, (button_id, label) in enumerate(row):
            markup = global_action_markup(label)
            if index < len(row) - 1:
                markup = f"{markup} [dim]|[/]"
            controls.append(
                Button(
                    markup,
                    id=button_id,
                    classes="global-action-button",
                    compact=True,
                    flat=True,
                )
            )
        return Horizontal(*controls, classes="global-action-row")

    def _current_global_action_width(self) -> int | None:
        app_width = getattr(getattr(self, "size", None), "width", None)
        width = action_layout_width(
            container_width=None,
            app_width=app_width,
            cached_width=self._last_global_action_width,
        )
        if isinstance(width, int) and width > 0:
            self._last_global_action_width = width
            return width
        return None

    def _refresh_global_action_buttons(self) -> None:
        try:
            terminal_width = self._current_global_action_width()
            if terminal_width == getattr(self, "_rendered_global_action_width", None):
                return
            rows = layout_action_button_rows(
                GLOBAL_ACTION_BUTTONS,
                available_width=terminal_width,
                preferred_rows=2,
            )
            self._rendered_global_action_width = terminal_width
            container = self.query_one("#global-actions")
            container.remove_children()
            for row in rows[:4]:
                container.mount(self._global_button_row(row))
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        self.status_message = str(text or "").strip() or "Ready"
        try:
            self.query_one("#status", Static).update(self.status_message)
        except Exception:
            pass

    def _reset_entry_input(self) -> None:
        try:
            self._apply_input_reset_state(tui_input_reset_state())
        except Exception:
            pass

    def _focus_items(self) -> None:
        try:
            self.query_one("#items", ListView).focus()
        except Exception:
            pass

    def _focus_run_button(self) -> None:
        try:
            self.query_one("#run", Button).focus()
        except Exception:
            self._focus_items()
