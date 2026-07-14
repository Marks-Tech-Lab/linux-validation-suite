from __future__ import annotations

from typing import Dict, List, Optional


class SettingsListEditorMixin:
    """CLI editors for settings-backed picker lists."""

    def settings_text_list(self, title: str, attr_name: str, defaults: List[str]) -> None:
        settings = self.settings_manager.settings
        while True:
            current = self._normalize_text_list(getattr(settings, attr_name), defaults)
            setattr(settings, attr_name, current)
            print(f"\n{title}")
            for index, item in enumerate(current, start=1):
                print(f"{index}. {item}")
            print("A. Add item")
            print("R. Rename item")
            print("D. Delete item")
            print("F. Restore defaults")
            print("B. Back")
            choice = self._input("Select: ").strip().lower()
            if choice == "a":
                raw = self._input("New item text: ").strip()
                if raw:
                    current.append(raw)
                    setattr(settings, attr_name, self._normalize_text_list(current, defaults))
            elif choice == "r":
                index = self.choose_text_list_index(current)
                if index is None:
                    continue
                raw = self._input(f"New text for '{current[index]}': ").strip()
                if raw:
                    current[index] = raw
                    setattr(settings, attr_name, self._normalize_text_list(current, defaults))
            elif choice == "d":
                index = self.choose_text_list_index(current)
                if index is None:
                    continue
                removed = current[index]
                raw = self._input(f"Delete '{removed}' from this picker list? [y/N]: ").strip().lower()
                if raw in {"y", "yes"}:
                    del current[index]
                    setattr(settings, attr_name, self._normalize_text_list(current, defaults))
            elif choice == "f":
                raw = self._input(f"Restore default {title.lower()}? [y/N]: ").strip().lower()
                if raw in {"y", "yes"}:
                    setattr(settings, attr_name, list(defaults))
            elif choice == "b":
                self.settings_manager.save()
                self._reload_runtime_state()
                print("Settings saved.")
                return
            else:
                print("Invalid selection.")
                continue
            self.settings_manager.save()
            self._reload_runtime_state()
            settings = self.settings_manager.settings
            print("Settings saved.")

    def choose_text_list_index(self, values: List[str]) -> Optional[int]:
        raw = self._input("Choose item number: ").strip()
        try:
            index = int(raw) - 1
        except Exception:
            print("Invalid item number.")
            return None
        if index < 0 or index >= len(values):
            print("Invalid item number.")
            return None
        return index

    def settings_profile_menu_groups(self) -> None:
        while True:
            groups = self.settings_facade.profile_menu_groups()
            print("\nProfile Menu Groups")
            for index, item in enumerate(groups, start=1):
                print(f"{index}. {item['label']} ({item['key']})")
            print("A. Add group")
            print("R. Rename group label")
            print("D. Delete group from picker list")
            print("F. Restore default group list")
            print("B. Back")
            choice = self._input("Select: ").strip().lower()
            if choice == "a":
                raw_key = self._input("New group key (example: repair_lab): ").strip()
                if not raw_key:
                    print("Group key required.")
                    continue
                raw_label = self._input("Group label shown in profile picker: ").strip()
                try:
                    self.settings_facade.add_profile_menu_group(raw_key, raw_label)
                except ValueError as exc:
                    print(str(exc))
                    continue
            elif choice == "r":
                index = self.choose_profile_menu_group_list_index(groups)
                if index is None:
                    continue
                current = groups[index]
                raw_label = self._input(f"New label for {current['key']} [{current['label']}]: ").strip()
                self.settings_facade.rename_profile_menu_group(index, raw_label)
            elif choice == "d":
                index = self.choose_profile_menu_group_list_index(groups)
                if index is None:
                    continue
                removed = groups[index]
                raw = self._input(
                    f"Remove '{removed['key']}' from the picker list? Profiles using it keep that value. [y/N]: "
                ).strip().lower()
                if raw not in {"y", "yes"}:
                    print("Remove cancelled.")
                    continue
                self.settings_facade.delete_profile_menu_group(index)
                print(
                    f"Removed '{removed['key']}' from the picker list. Existing profiles with that group are unchanged "
                    + "and will display as unlisted until the group is added again."
                )
            elif choice == "f":
                raw = self._input("Restore the default profile menu group list? [y/N]: ").strip().lower()
                if raw in {"y", "yes"}:
                    self.settings_facade.restore_profile_menu_group_defaults()
            elif choice == "b":
                self.settings_manager.save()
                self._reload_runtime_state()
                print("Settings saved.")
                return
            else:
                print("Invalid selection.")
                continue
            self.settings_manager.save()
            self._reload_runtime_state()
            print("Settings saved.")

    def choose_profile_menu_group_list_index(self, groups: List[Dict[str, str]]) -> Optional[int]:
        raw = self._input("Choose group number: ").strip()
        try:
            index = int(raw) - 1
        except Exception:
            print("Invalid group number.")
            return None
        if index < 0 or index >= len(groups):
            print("Invalid group number.")
            return None
        return index
