import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "niri_integration", ROOT / "bin/niri_integration.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BEGIN = "// BEGIN MATUGEN THEME SYNC"
END = "// END MATUGEN THEME SYNC"


class ManagedBlockTests(unittest.TestCase):
    def test_upsert_appends_exactly_one_block(self):
        result = MODULE.upsert_managed_block("layout {}\n", BEGIN, END, 'include "./colors.kdl"')
        self.assertEqual(result.count(BEGIN), 1)
        self.assertTrue(result.endswith(f'{BEGIN}\ninclude "./colors.kdl"\n{END}\n'))

    def test_upsert_replaces_existing_body(self):
        old = f"header\n{BEGIN}\nold\n{END}\nfooter\n"
        result = MODULE.upsert_managed_block(old, BEGIN, END, "new")
        self.assertEqual(result, f"header\n{BEGIN}\nnew\n{END}\nfooter\n")

    def test_remove_preserves_surrounding_edits(self):
        text = f"before\n{BEGIN}\nmanaged\n{END}\nafter\n"
        self.assertEqual(MODULE.remove_managed_block(text, BEGIN, END), "before\nafter\n")

    def test_partial_or_duplicate_markers_raise(self):
        cases = (f"{BEGIN}\nbody\n", f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}\n")
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(MODULE.ManagedBlockError):
                    MODULE.upsert_managed_block(text, BEGIN, END, "new")

    def test_end_before_begin_is_rejected_by_upsert_and_remove(self):
        text = f"header\n{END}\n{BEGIN}\nbody\n"
        with self.assertRaises(MODULE.ManagedBlockError):
            MODULE.upsert_managed_block(text, BEGIN, END, "new")
        with self.assertRaises(MODULE.ManagedBlockError):
            MODULE.remove_managed_block(text, BEGIN, END)

    def test_embedded_marker_is_rejected_by_upsert_and_remove(self):
        text = f"header {BEGIN}\nbody\n{END}\n"
        with self.assertRaises(MODULE.ManagedBlockError):
            MODULE.upsert_managed_block(text, BEGIN, END, "new")
        with self.assertRaises(MODULE.ManagedBlockError):
            MODULE.remove_managed_block(text, BEGIN, END)


class NiriIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.state = self.base / "state"
        self.resources = self.base / "resources"
        (self.resources / "waybar").mkdir(parents=True)
        (self.resources / "rofi").mkdir()
        (self.resources / "mako").mkdir()
        (self.resources / "waybar/style.css").write_text(
            '@import url("@MATUGEN_WAYBAR_COLORS@");\n', encoding="utf-8"
        )
        (self.resources / "rofi/matugen.rasi").write_text(
            '@import "../colors.rasi"\n', encoding="utf-8"
        )
        (self.resources / "mako/config").write_text(
            "include=@MATUGEN_MAKO_COLORS@\n", encoding="utf-8"
        )
        self.manager = MODULE.NiriIntegration(
            self.home,
            self.state,
            self.resources,
            timestamp=lambda: "20260901T120000",
        )

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def apply_and_commit(self):
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.activate()
        self.manager.commit()

    def test_first_apply_keeps_immutable_original_and_is_idempotent(self):
        style = self.write(".config/waybar/style.css", "original-style\n")
        niri = self.write(".config/niri/config.kdl", "layout {}\n")
        rofi = self.write(".config/rofi/config.rasi", "configuration {}\n")
        self.apply_and_commit()
        manifest_path = self.state / "matugen-theme-sync/niri/manifest.json"
        first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn(
            str(style), [item["path"] for item in first_manifest["targets"].values()]
        )
        self.assertIn('include "./colors.kdl"', niri.read_text(encoding="utf-8"))
        self.assertIn('@theme "matugen"', rofi.read_text(encoding="utf-8"))
        original = self.state / "matugen-theme-sync/niri/originals/waybar-style"
        self.assertEqual(original.read_text(encoding="utf-8"), "original-style\n")

        self.apply_and_commit()

        second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(first_manifest["targets"], second_manifest["targets"])
        self.assertEqual(original.read_text(encoding="utf-8"), "original-style\n")

    def test_failed_apply_rolls_back_to_pre_operation_state(self):
        style = self.write(".config/waybar/style.css", "before-operation\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.assertNotEqual(style.read_text(encoding="utf-8"), "before-operation\n")
        self.manager.rollback()
        self.assertEqual(style.read_text(encoding="utf-8"), "before-operation\n")
        self.assertFalse(self.manager.transaction.exists())

    def test_rollback_removes_a_target_that_was_absent_at_begin(self):
        style = self.home / ".config/waybar/style.css"
        self.manager.begin()
        self.manager.deploy_static()
        self.assertTrue(style.exists())
        self.manager.rollback()
        self.assertFalse(style.exists())

    def test_begin_recovers_a_leftover_transaction_before_snapshotting(self):
        style = self.write(".config/waybar/style.css", "before-crash\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.assertNotEqual(style.read_text(encoding="utf-8"), "before-crash\n")

        recovered = MODULE.NiriIntegration(
            self.home,
            self.state,
            self.resources,
            timestamp=lambda: "20260901T120001",
        )
        recovered.begin()

        self.assertEqual(style.read_text(encoding="utf-8"), "before-crash\n")
        recovered.rollback()
        self.assertEqual(style.read_text(encoding="utf-8"), "before-crash\n")

    def test_changed_managed_file_is_archived_before_update(self):
        style = self.write(".config/waybar/style.css", "original\n")
        self.apply_and_commit()
        style.write_text("user-managed-edit\n", encoding="utf-8")
        self.manager.begin()
        self.manager.deploy_static()
        conflict = self.state / (
            "matugen-theme-sync/niri/conflicts/20260901T120000/waybar-style"
        )
        self.assertEqual(conflict.read_text(encoding="utf-8"), "user-managed-edit\n")
        self.manager.rollback()

    def test_generated_files_are_restored_without_conflict_archives(self):
        generated = self.write(".config/niri/colors.kdl", "original-colors\n")
        self.manager.begin()
        generated.write_text("first-generated\n", encoding="utf-8")
        self.manager.activate()
        self.manager.commit()
        self.manager.begin()
        generated.write_text("user-generated-edit\n", encoding="utf-8")
        self.manager.commit()

        self.manager.restore()

        self.assertEqual(generated.read_text(encoding="utf-8"), "original-colors\n")
        conflicts = self.state / "matugen-theme-sync/niri/conflicts"
        self.assertFalse(conflicts.exists())

    def test_static_deployment_resolves_only_absolute_color_placeholders(self):
        self.manager.begin()
        self.manager.deploy_static()

        waybar = self.home / ".config/waybar/style.css"
        rofi = self.home / ".config/rofi/themes/matugen.rasi"
        mako = self.home / ".config/mako/config"
        self.assertEqual(
            waybar.read_text(encoding="utf-8"),
            f'@import url("{self.home}/.config/waybar/colors.css");\n',
        )
        self.assertEqual(rofi.read_text(encoding="utf-8"), '@import "../colors.rasi"\n')
        self.assertEqual(
            mako.read_text(encoding="utf-8"),
            f"include={self.home}/.config/mako/colors\n",
        )
        self.manager.rollback()

    def test_unresolved_static_marker_aborts_without_overwriting_target(self):
        style = self.write(".config/waybar/style.css", "before\n")
        (self.resources / "waybar/style.css").write_text(
            "@MATUGEN_UNKNOWN@\n", encoding="utf-8"
        )
        self.manager.begin()

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.deploy_static()

        self.assertEqual(style.read_text(encoding="utf-8"), "before\n")
        self.manager.rollback()

    def test_atomic_updates_and_rollback_preserve_file_modes(self):
        style = self.write(".config/waybar/style.css", "original\n")
        os.chmod(style, 0o4750)
        self.manager.begin()
        self.manager.deploy_static()
        self.assertEqual(stat.S_IMODE(style.stat().st_mode), 0o4750)
        os.chmod(style, 0o600)

        self.manager.rollback()

        self.assertEqual(style.read_text(encoding="utf-8"), "original\n")
        self.assertEqual(stat.S_IMODE(style.stat().st_mode), 0o4750)

    def test_restore_restores_originals_removes_absent_paths_and_preserves_new_config(self):
        style = self.write(".config/waybar/style.css", "original-style\n")
        niri = self.write(".config/niri/config.kdl", "layout {}\n")
        rofi = self.write(".config/rofi/config.rasi", "configuration {}\n")
        self.manager.begin()
        self.manager.deploy_static()
        generated = self.write(".config/niri/colors.kdl", "generated\n")
        self.manager.activate()
        self.manager.commit()
        niri.write_text(
            niri.read_text(encoding="utf-8") + "// later-niri-edit\n",
            encoding="utf-8",
        )
        rofi.write_text(
            rofi.read_text(encoding="utf-8") + "/* later-rofi-edit */\n",
            encoding="utf-8",
        )
        self.manager.restore()
        self.assertEqual(style.read_text(encoding="utf-8"), "original-style\n")
        self.assertFalse(generated.exists())
        self.assertNotIn(MODULE.NIRI_BEGIN, niri.read_text(encoding="utf-8"))
        self.assertIn("later-niri-edit", niri.read_text(encoding="utf-8"))
        self.assertNotIn(MODULE.ROFI_BEGIN, rofi.read_text(encoding="utf-8"))
        self.assertIn("later-rofi-edit", rofi.read_text(encoding="utf-8"))

    def test_malformed_block_is_archived_then_original_is_restored(self):
        niri = self.write(".config/niri/config.kdl", "layout {}\n")
        self.apply_and_commit()
        malformed = f"layout {{}}\n{MODULE.NIRI_BEGIN}\nuser-edit-without-end\n"
        niri.write_text(malformed, encoding="utf-8")

        self.manager.restore()

        conflict = self.state / (
            "matugen-theme-sync/niri/conflicts/20260901T120000/niri-config"
        )
        self.assertEqual(conflict.read_text(encoding="utf-8"), malformed)
        self.assertEqual(niri.read_text(encoding="utf-8"), "layout {}\n")

    def test_restore_recovers_an_original_patched_config_deleted_after_apply(self):
        niri = self.write(".config/niri/config.kdl", "layout {}\n")
        self.apply_and_commit()
        niri.unlink()

        self.manager.restore()

        self.assertEqual(niri.read_text(encoding="utf-8"), "layout {}\n")

    def test_restore_cleans_managed_state_but_preserves_conflicts(self):
        style = self.write(".config/waybar/style.css", "original\n")
        self.apply_and_commit()
        style.write_text("edited\n", encoding="utf-8")
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.commit()
        self.manager.restore()

        root = self.state / "matugen-theme-sync/niri"
        self.assertFalse((root / "manifest.json").exists())
        self.assertFalse((root / "originals").exists())
        self.assertFalse((root / "transactions").exists())
        self.assertEqual(
            (root / "conflicts/20260901T120000/waybar-style").read_text(
                encoding="utf-8"
            ),
            "edited\n",
        )

    def test_validate_runs_installed_validators_and_rejects_parse_failures(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            stderr = "Failed to parse config" if command[0] == "rofi" else ""
            return SimpleNamespace(returncode=0, stderr=stderr)

        with patch.object(
            MODULE.shutil, "which", side_effect=lambda name: f"/bin/{name}"
        ):
            with self.assertRaises(MODULE.IntegrationError):
                self.manager.validate(run)

        self.assertEqual([call[0][0] for call in calls], ["niri", "rofi"])
        self.assertTrue(
            all(
                kwargs == {"capture_output": True, "text": True}
                for _, kwargs in calls
            )
        )

    def test_validate_skips_absent_optional_applications(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stderr="")

        with patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda name: "/bin/mako" if name == "mako" else None,
        ):
            self.manager.validate(run)

        self.assertEqual([command[0] for command in calls], ["mako"])

    def test_reload_returns_warnings_and_continues_after_failures(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=1 if command[0] != "makoctl" else 0)

        with patch.object(MODULE.shutil, "which", return_value="/bin/tool"):
            warnings = self.manager.reload(run)

        self.assertEqual(
            [command[0] for command in calls], ["niri", "pkill", "makoctl"]
        )
        self.assertEqual(warnings, ["could not reload niri", "could not reload pkill"])
