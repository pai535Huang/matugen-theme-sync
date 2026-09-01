import binascii
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
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

    def write_generated_targets(self, suffix="original"):
        return {
            key: self.write(relative, f"{key}-{suffix}\n")
            for key, (relative, kind) in MODULE.TARGETS.items()
            if kind == "generated"
        }

    def write_missing_generated_targets(self):
        for key, (relative, kind) in MODULE.TARGETS.items():
            target = self.home / relative
            if kind == "generated" and not target.exists():
                self.write(relative, f"{key}-generated\n")

    def apply_and_commit(self):
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.activate()
        self.write_missing_generated_targets()
        self.manager.commit()

    def assert_lifecycle_lock_available(self):
        descriptor = os.open(self.manager.lock_path, os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.fail("lifecycle lock remained held after a terminal path")
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

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
        # A real process crash closes the flock descriptor while leaving the
        # transaction journal behind.
        self.manager._release_lifecycle_lock()

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
        self.assertEqual(style.read_text(encoding="utf-8"), "user-managed-edit\n")

    def test_failed_first_apply_retry_archives_edit_and_restore_keeps_conflict(self):
        style = self.write(".config/waybar/style.css", "immutable-original\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.rollback()
        style.write_text("edit-after-failed-apply\n", encoding="utf-8")

        self.manager.begin()
        self.manager.deploy_static()
        conflict = self.state / (
            "matugen-theme-sync/niri/conflicts/20260901T120000/waybar-style"
        )
        self.assertEqual(
            conflict.read_text(encoding="utf-8"), "edit-after-failed-apply\n"
        )
        self.manager.rollback()
        self.assertEqual(style.read_text(encoding="utf-8"), "edit-after-failed-apply\n")

        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        self.manager.commit()
        self.manager.restore()

        self.assertEqual(style.read_text(encoding="utf-8"), "immutable-original\n")
        self.assertEqual(
            conflict.read_text(encoding="utf-8"), "edit-after-failed-apply\n"
        )

    def test_retry_archives_mode_only_edit_when_no_deployed_checksum_exists(self):
        style = self.write(".config/waybar/style.css", "unchanged-bytes\n")
        os.chmod(style, 0o640)
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.rollback()
        os.chmod(style, 0o600)

        self.manager.begin()
        self.manager.deploy_static()

        conflict = self.state / (
            "matugen-theme-sync/niri/conflicts/20260901T120000/waybar-style"
        )
        self.assertEqual(conflict.read_text(encoding="utf-8"), "unchanged-bytes\n")
        self.assertEqual(stat.S_IMODE(conflict.stat().st_mode), 0o600)
        self.manager.rollback()
        self.assertEqual(stat.S_IMODE(style.stat().st_mode), 0o600)

    def test_retry_records_deleted_original_before_recreating_static_target(self):
        style = self.write(".config/waybar/style.css", "immutable-original\n")
        os.chmod(style, 0o640)
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.rollback()
        style.unlink()

        self.manager.begin()
        self.manager.deploy_static()

        absent = self.state / (
            "matugen-theme-sync/niri/conflicts/20260901T120000/"
            "waybar-style.absent"
        )
        self.assertEqual(absent.read_bytes(), b"")
        self.assertEqual(stat.S_IMODE(absent.stat().st_mode), 0o644)
        self.write_missing_generated_targets()
        self.manager.commit()
        self.manager.restore()
        self.assertEqual(style.read_text(encoding="utf-8"), "immutable-original\n")
        self.assertEqual(stat.S_IMODE(style.stat().st_mode), 0o640)
        self.assertEqual(absent.read_bytes(), b"")

    def test_atomic_write_fsyncs_file_before_replace_and_parent_after_replace(self):
        target = self.base / "durability/manifest.json"
        target.parent.mkdir()
        events = []
        real_fsync = MODULE.os.fsync
        real_replace = MODULE.os.replace

        def record_fsync(descriptor):
            kind = "dir" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            events.append(("fsync", kind, os.readlink(f"/proc/self/fd/{descriptor}")))
            return real_fsync(descriptor)

        def record_replace(source, destination):
            events.append(("replace", str(Path(destination))))
            return real_replace(source, destination)

        with patch.object(MODULE.os, "fsync", side_effect=record_fsync), patch.object(
            MODULE.os, "replace", side_effect=record_replace
        ):
            self.manager._atomic_write(target, "durable\n")

        file_sync = next(i for i, event in enumerate(events) if event[0:2] == ("fsync", "file"))
        replacement = events.index(("replace", str(target)))
        parent_syncs = [
            i
            for i, event in enumerate(events)
            if event[0:2] == ("fsync", "dir")
            and Path(event[2]) == target.parent
        ]
        self.assertTrue(parent_syncs, "atomic replacement did not fsync its parent")
        parent_sync = parent_syncs[0]
        self.assertLess(file_sync, replacement)
        self.assertLess(replacement, parent_sync)

    def test_begin_publishes_complete_preparing_snapshot_durably_before_current(self):
        self.write(".config/waybar/style.css", "original\n")
        events = []
        real_fsync = MODULE.os.fsync
        real_replace = MODULE.os.replace

        def record_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                events.append(("fsync-dir", os.readlink(f"/proc/self/fd/{descriptor}")))
            return real_fsync(descriptor)

        def record_replace(source, destination):
            events.append(("replace", str(Path(source)), str(Path(destination))))
            return real_replace(source, destination)

        with patch.object(MODULE.os, "fsync", side_effect=record_fsync), patch.object(
            MODULE.os, "replace", side_effect=record_replace
        ):
            self.manager.begin()

        preparing = self.manager.root / "transactions/preparing"
        metadata = preparing / "metadata.json"
        transactions = self.manager.root / "transactions"
        metadata_replace = next(
            i
            for i, event in enumerate(events)
            if event[0] == "replace" and Path(event[2]) == metadata
        )
        preparing_syncs = [
            i
            for i, event in enumerate(events[metadata_replace + 1 :], metadata_replace + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == preparing
        ]
        self.assertTrue(preparing_syncs, "preparing contents were not directory-fsynced")
        preparing_sync = preparing_syncs[0]
        current_replace = next(
            i
            for i, event in enumerate(events)
            if event[0] == "replace" and Path(event[2]) == self.manager.transaction
        )
        transaction_syncs = [
            i
            for i, event in enumerate(events[current_replace + 1 :], current_replace + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == transactions
        ]
        self.assertTrue(transaction_syncs, "current rename was not directory-fsynced")
        transaction_sync = transaction_syncs[0]
        self.assertLess(metadata_replace, preparing_sync)
        self.assertLess(preparing_sync, current_replace)
        self.assertLess(current_replace, transaction_sync)
        self.manager.rollback()

    def test_begin_durably_publishes_original_before_manifest(self):
        self.write(".config/waybar/style.css", "original\n")
        events = []
        real_fsync = MODULE.os.fsync
        real_replace = MODULE.os.replace

        def record_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                events.append(("fsync-dir", os.readlink(f"/proc/self/fd/{descriptor}")))
            return real_fsync(descriptor)

        def record_replace(source, destination):
            events.append(("replace", str(Path(destination))))
            return real_replace(source, destination)

        with patch.object(MODULE.os, "fsync", side_effect=record_fsync), patch.object(
            MODULE.os, "replace", side_effect=record_replace
        ):
            self.manager.begin()

        original = self.manager.root / "originals/waybar-style"
        original_replace = events.index(("replace", str(original)))
        original_sync = next(
            i
            for i, event in enumerate(events[original_replace + 1 :], original_replace + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == original.parent
        )
        manifest_replace = events.index(("replace", str(self.manager.manifest_path)))
        manifest_sync = next(
            i
            for i, event in enumerate(events[manifest_replace + 1 :], manifest_replace + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == self.manager.root
        )
        self.assertLess(original_replace, original_sync)
        self.assertLess(original_sync, manifest_replace)
        self.assertLess(manifest_replace, manifest_sync)
        self.manager.rollback()

    def test_commit_fsyncs_cleanup_before_removing_recovery_journal(self):
        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        events = []
        real_fsync = MODULE.os.fsync
        real_rmtree = MODULE.shutil.rmtree
        real_unlink = Path.unlink

        def record_fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                events.append(("fsync-dir", os.readlink(f"/proc/self/fd/{descriptor}")))
            return real_fsync(descriptor)

        def record_rmtree(path, *args, **kwargs):
            events.append(("rmtree", str(Path(path))))
            return real_rmtree(path, *args, **kwargs)

        def record_unlink(path, *args, **kwargs):
            events.append(("unlink", str(path)))
            return real_unlink(path, *args, **kwargs)

        with patch.object(MODULE.os, "fsync", side_effect=record_fsync), patch.object(
            MODULE.shutil, "rmtree", side_effect=record_rmtree
        ), patch.object(Path, "unlink", record_unlink):
            self.manager.commit()

        transactions = self.manager.root / "transactions"
        cleanup_index = events.index(("rmtree", str(self.manager.committed_cleanup_path)))
        cleanup_syncs = [
            i
            for i, event in enumerate(events[cleanup_index + 1 :], cleanup_index + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == transactions
        ]
        self.assertTrue(cleanup_syncs, "cleanup removal was not directory-fsynced")
        cleanup_sync = cleanup_syncs[0]
        journal_unlink = events.index(("unlink", str(self.manager.committed_manifest_path)))
        journal_syncs = [
            i
            for i, event in enumerate(events[journal_unlink + 1 :], journal_unlink + 1)
            if event[0] == "fsync-dir" and Path(event[1]) == transactions
        ]
        self.assertTrue(journal_syncs, "journal unlink was not directory-fsynced")
        journal_sync = journal_syncs[0]
        self.assertLess(cleanup_index, cleanup_sync)
        self.assertLess(cleanup_sync, journal_unlink)
        self.assertLess(journal_unlink, journal_sync)

    def test_commit_syncs_generated_targets_before_publishing_journal(self):
        generated = self.write_generated_targets()
        self.manager.begin()
        events = []
        real_fsync_file = getattr(self.manager, "_fsync_file", lambda path: None)
        real_fsync_directory = self.manager._fsync_directory
        real_atomic_write = self.manager._atomic_write
        keys_by_path = {path: key for key, path in generated.items()}
        keys_by_parent = {path.parent: key for key, path in generated.items()}

        def record_file(path):
            events.append(f"file:{keys_by_path[Path(path)]}")
            return real_fsync_file(path)

        def record_directory(path):
            path = Path(path)
            if path in keys_by_parent:
                events.append(f"dir:{keys_by_parent[path]}")
            return real_fsync_directory(path)

        def record_atomic_write(path, data, mode=0o644):
            if Path(path) == self.manager.committed_manifest_path:
                events.append("journal")
            return real_atomic_write(path, data, mode)

        with patch.object(
            self.manager, "_fsync_file", side_effect=record_file, create=True
        ), patch.object(
            self.manager, "_fsync_directory", side_effect=record_directory
        ), patch.object(
            self.manager, "_atomic_write", side_effect=record_atomic_write
        ):
            self.manager.commit()

        expected = {
            "niri-colors",
            "waybar-colors",
            "rofi-colors",
            "mako-colors",
        }
        synced = {
            event.removeprefix("file:")
            for event in events
            if event.startswith("file:")
        }
        self.assertEqual(synced, expected)
        for key in expected:
            self.assertLess(events.index(f"file:{key}"), events.index("journal"))
            self.assertLess(events.index(f"dir:{key}"), events.index("journal"))

    def test_commit_rejects_missing_generated_target_before_journal(self):
        generated = self.write_generated_targets()
        self.manager.begin()
        generated["niri-colors"].unlink()

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.commit()

        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertTrue(self.manager.transaction.is_dir())
        self.manager.rollback()

    def test_commit_rejects_generated_symlink_before_journal(self):
        generated = self.write_generated_targets()
        self.manager.begin()
        target = generated["waybar-colors"]
        target.unlink()
        target.symlink_to(generated["niri-colors"])

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.commit()

        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertTrue(self.manager.transaction.is_dir())
        target.unlink()
        self.manager.rollback()

    def test_commit_rejects_non_regular_generated_target_before_journal(self):
        generated = self.write_generated_targets()
        self.manager.begin()
        target = generated["rofi-colors"]
        target.unlink()
        target.mkdir()

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.commit()

        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertTrue(self.manager.transaction.is_dir())
        target.rmdir()
        self.manager.rollback()

    def test_generated_sync_failure_remains_rollbackable(self):
        generated = self.write_generated_targets()
        original = {
            key: path.read_text(encoding="utf-8")
            for key, path in generated.items()
        }
        self.manager.begin()
        for key, path in generated.items():
            path.write_text(f"{key}-generated\n", encoding="utf-8")

        with patch.object(
            self.manager,
            "_fsync_file",
            side_effect=OSError("injected generated file fsync failure"),
            create=True,
        ):
            with self.assertRaises(OSError):
                self.manager.commit()

        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertTrue(self.manager.transaction.is_dir())
        self.manager.rollback()
        self.assertEqual(
            {key: path.read_text(encoding="utf-8") for key, path in generated.items()},
            original,
        )

    def test_commit_recovers_directory_fsync_failure_before_journal_removal(self):
        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        real_fsync = MODULE.os.fsync
        real_rmtree = MODULE.shutil.rmtree
        failed_once = False
        cleanup_removed = False

        def record_cleanup(path, *args, **kwargs):
            nonlocal cleanup_removed
            result = real_rmtree(path, *args, **kwargs)
            if Path(path) == self.manager.committed_cleanup_path:
                cleanup_removed = True
            return result

        def fail_cleanup_directory_sync_once(descriptor):
            nonlocal failed_once
            descriptor_path = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
            if (
                stat.S_ISDIR(os.fstat(descriptor).st_mode)
                and descriptor_path == self.manager.root / "transactions"
                and self.manager.committed_manifest_path.exists()
                and cleanup_removed
                and not failed_once
            ):
                failed_once = True
                raise OSError("injected transaction directory fsync failure")
            return real_fsync(descriptor)

        with patch.object(
            MODULE.shutil, "rmtree", side_effect=record_cleanup
        ), patch.object(MODULE.os, "fsync", side_effect=fail_cleanup_directory_sync_once):
            warning = self.manager.commit()

        self.assertTrue(failed_once)
        self.assertIn("durable", warning)
        self.assertFalse(self.manager.committed_manifest_path.exists())

    def test_process_lifecycle_lock_prevents_recovery_of_a_live_transaction(self):
        helper = r'''
import importlib.util
import pathlib
import sys
import time

module_path, home, state, resources, ready, release = sys.argv[1:]
spec = importlib.util.spec_from_file_location("niri_integration_child", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
manager = module.NiriIntegration(pathlib.Path(home), pathlib.Path(state), pathlib.Path(resources))
manager.begin()
pathlib.Path(ready).write_text("ready\n", encoding="utf-8")
if release != "-":
    while not pathlib.Path(release).exists():
        time.sleep(0.01)
manager.rollback()
'''
        first_ready = self.base / "first.ready"
        first_release = self.base / "first.release"
        second_ready = self.base / "second.ready"
        arguments = [
            sys.executable,
            "-c",
            helper,
            str(ROOT / "bin/niri_integration.py"),
            str(self.home),
            str(self.state),
            str(self.resources),
        ]
        first = subprocess.Popen(
            arguments + [str(first_ready), str(first_release)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        second = None
        try:
            deadline = time.monotonic() + 3
            while not first_ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(first_ready.exists(), first.stderr.read() if first.poll() is not None else "")

            second = subprocess.Popen(
                arguments + [str(second_ready), "-"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            time.sleep(0.25)
            self.assertFalse(
                second_ready.exists(),
                "a second lifecycle entered while the first transaction was live",
            )
            first_release.touch()
            first_stdout, first_stderr = first.communicate(timeout=3)
            second_stdout, second_stderr = second.communicate(timeout=3)
            self.assertEqual(first.returncode, 0, first_stdout + first_stderr)
            self.assertEqual(second.returncode, 0, second_stdout + second_stderr)
            self.assertTrue(second_ready.exists())
        finally:
            first_release.touch(exist_ok=True)
            for process in (first, second):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_lifecycle_lock_is_stable_and_released_on_terminal_paths(self):
        self.manager.begin()
        lock_inode = self.manager.lock_path.stat().st_ino
        self.assertNotIn(self.manager.root, self.manager.lock_path.parents)
        self.manager.rollback()
        self.assert_lifecycle_lock_available()

        self.manager.begin()
        self.write_missing_generated_targets()
        self.manager.commit()
        self.assert_lifecycle_lock_available()
        self.manager.restore()
        self.assert_lifecycle_lock_available()
        self.assertEqual(self.manager.lock_path.stat().st_ino, lock_inode)

        invalid = self.home / ".config/niri/config.kdl"
        invalid.mkdir(parents=True)
        with self.assertRaises(MODULE.IntegrationError):
            self.manager.begin()
        self.assert_lifecycle_lock_available()

    def test_commit_recovers_one_post_journal_manifest_failure(self):
        style = self.write(".config/waybar/style.css", "original\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        deployed = style.read_bytes()
        expected_checksum = hashlib.sha256(deployed).hexdigest()
        real_replace = MODULE.os.replace
        failed_once = False

        def fail_manifest_replace(source, destination):
            nonlocal failed_once
            if (
                Path(destination) == self.manager.manifest_path
                and self.manager.committed_manifest_path.is_file()
                and not failed_once
            ):
                failed_once = True
                raise OSError("injected manifest replacement failure")
            return real_replace(source, destination)

        with patch.object(MODULE.os, "replace", side_effect=fail_manifest_replace):
            try:
                warning = self.manager.commit()
            except OSError as exc:
                self.fail(f"post-journal manifest failure was not recovered: {exc}")

        manifest = json.loads(self.manager.manifest_path.read_text(encoding="utf-8"))
        self.assertIn("durable", warning)
        self.assertEqual(style.read_bytes(), deployed)
        self.assertEqual(
            manifest["targets"]["waybar-style"]["deployed_checksum"],
            expected_checksum,
        )
        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertFalse(self.manager.committed_cleanup_path.exists())
        self.assertFalse(self.manager.transaction.exists())

    def test_commit_recovers_one_post_journal_cleanup_failure(self):
        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        cleanup = self.manager.committed_cleanup_path
        real_rmtree = MODULE.shutil.rmtree
        failed_once = False

        def fail_cleanup_once(path, *args, **kwargs):
            nonlocal failed_once
            if Path(path) == cleanup and not failed_once:
                failed_once = True
                raise OSError("injected cleanup failure")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(MODULE.shutil, "rmtree", side_effect=fail_cleanup_once):
            try:
                warning = self.manager.commit()
            except OSError as exc:
                self.fail(f"post-journal cleanup failure was not recovered: {exc}")

        self.assertIn("durable", warning)
        self.assertFalse(self.manager.committed_manifest_path.exists())
        self.assertFalse(cleanup.exists())
        self.assertFalse(self.manager.transaction.exists())

    def interrupt_commit_during_partial_cleanup(self):
        style = self.write(".config/waybar/style.css", "original\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.write_missing_generated_targets()
        deployed = style.read_bytes()
        expected_checksum = hashlib.sha256(deployed).hexdigest()
        transactions = self.manager.root / "transactions"
        cleanup = transactions / "committed-cleanup"
        journal = transactions / "committed-manifest.json"
        real_rmtree = MODULE.shutil.rmtree

        def fail_transaction_cleanup(path, *args, **kwargs):
            if Path(path) == cleanup:
                (cleanup / "waybar-style").unlink()
                raise OSError("injected partial transaction cleanup failure")
            return real_rmtree(path, *args, **kwargs)

        with patch.object(
            MODULE.shutil, "rmtree", side_effect=fail_transaction_cleanup
        ):
            with self.assertRaises(MODULE.DurableCommitError) as raised:
                self.manager.commit()
        self.assertIn("pending recovery", str(raised.exception))

        return style, deployed, expected_checksum, cleanup, journal

    def test_partial_commit_cleanup_keeps_journal_until_cleanup_succeeds(self):
        style, deployed, _, cleanup, journal = (
            self.interrupt_commit_during_partial_cleanup()
        )

        self.assertEqual(style.read_bytes(), deployed)
        self.assertTrue(cleanup.is_dir())
        self.assertFalse((cleanup / "waybar-style").exists())
        self.assertTrue(journal.is_file())
        self.assertFalse(self.manager.transaction.exists())
        self.assert_lifecycle_lock_available()

    def test_begin_converges_after_partial_committed_cleanup(self):
        style, deployed, expected_checksum, cleanup, journal = (
            self.interrupt_commit_during_partial_cleanup()
        )

        recovered = MODULE.NiriIntegration(
            self.home,
            self.state,
            self.resources,
            timestamp=lambda: "20260901T120001",
        )
        recovered.begin()

        manifest = json.loads(recovered.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(style.read_bytes(), deployed)
        self.assertEqual(
            manifest["targets"]["waybar-style"]["deployed_checksum"],
            expected_checksum,
        )
        self.assertFalse(cleanup.exists())
        self.assertFalse(journal.exists())
        style.write_text("next-operation-change\n", encoding="utf-8")
        recovered.rollback()
        self.assertEqual(style.read_bytes(), deployed)

    def test_begin_rejects_direct_target_symlink_without_state_changes(self):
        external = self.base / "external-style"
        external.write_text("external\n", encoding="utf-8")
        style = self.home / ".config/waybar/style.css"
        style.parent.mkdir(parents=True)
        style.symlink_to(external)

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.begin()

        self.assertTrue(style.is_symlink())
        self.assertEqual(external.read_text(encoding="utf-8"), "external\n")
        self.assertFalse(self.manager.root.exists())

    def test_begin_rejects_dangling_target_symlink_without_state_changes(self):
        style = self.home / ".config/waybar/style.css"
        style.parent.mkdir(parents=True)
        style.symlink_to(self.base / "missing-style")

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.begin()

        self.assertTrue(style.is_symlink())
        self.assertFalse(style.exists())
        self.assertFalse(self.manager.root.exists())

    def test_begin_rejects_symlinked_parent_without_state_changes(self):
        external = self.base / "external-waybar"
        external.mkdir()
        (external / "style.css").write_text("external\n", encoding="utf-8")
        waybar = self.home / ".config/waybar"
        waybar.parent.mkdir(parents=True)
        waybar.symlink_to(external, target_is_directory=True)

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.begin()

        self.assertTrue(waybar.is_symlink())
        self.assertEqual(
            (external / "style.css").read_text(encoding="utf-8"), "external\n"
        )
        self.assertFalse(self.manager.root.exists())

    def test_begin_rejects_non_regular_target_without_mutating_it(self):
        niri = self.home / ".config/niri/config.kdl"
        niri.mkdir(parents=True)

        with self.assertRaises(MODULE.IntegrationError):
            self.manager.begin()

        self.assertTrue(niri.is_dir())
        self.assertFalse(self.manager.root.exists())

    def test_generated_files_are_restored_without_conflict_archives(self):
        generated = self.write(".config/niri/colors.kdl", "original-colors\n")
        self.manager.begin()
        generated.write_text("first-generated\n", encoding="utf-8")
        self.manager.activate()
        self.write_missing_generated_targets()
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
        self.write_missing_generated_targets()
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

    def test_direct_restore_archives_deleted_patched_configs_before_originals(self):
        cases = (
            ("niri-config", ".config/niri/config.kdl", "layout {}\n"),
            ("rofi-config", ".config/rofi/config.rasi", "configuration {}\n"),
        )
        for key, relative, original in cases:
            with self.subTest(key=key):
                target = self.write(relative, original)
                self.apply_and_commit()
                target.unlink()

                self.manager.restore()

                marker = self.state / (
                    "matugen-theme-sync/niri/conflicts/20260901T120000/"
                    f"{key}.absent"
                )
                self.assertTrue(marker.is_file(), "deleted config was not archived")
                self.assertEqual(marker.read_bytes(), b"")
                self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_reapply_records_deleted_patched_configs_and_restore_recovers_originals(self):
        cases = (
            ("niri-config", ".config/niri/config.kdl", b"layout { focus-ring {} }\n"),
            (
                "rofi-config",
                ".config/rofi/config.rasi",
                b'configuration { modi: "drun"; }\n',
            ),
        )
        for key, relative, original in cases:
            with self.subTest(key=key):
                target = self.write(relative, original.decode("utf-8"))
                self.apply_and_commit()
                target.unlink()

                self.manager.begin()
                self.manager.activate()
                self.manager.commit()
                self.manager.restore()

                marker = self.state / (
                    "matugen-theme-sync/niri/conflicts/20260901T120000/"
                    f"{key}.absent"
                )
                self.assertEqual(target.read_bytes(), original)
                self.assertEqual(marker.read_bytes(), b"")

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
            try:
                self.manager.validate(run)
            except MODULE.IntegrationError as error:
                self.fail(f"connection failure was rejected as a parse error: {error}")

        self.assertEqual([command[0] for command in calls], ["mako"])

    def test_mako_validation_launches_config_without_help_in_isolated_session(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Failed to connect to user bus: No such file or directory\n",
            )

        with patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda name: "/bin/mako" if name == "mako" else None,
        ):
            self.manager.validate(run)

        self.assertEqual(
            calls[0][0], ["mako", "-c", str(self.home / ".config/mako/config")]
        )
        kwargs = calls[0][1]
        self.assertEqual(kwargs["timeout"], 2)
        self.assertEqual(kwargs["env"]["WAYLAND_DISPLAY"], "matugen-theme-sync-invalid")
        self.assertIn("validation-no-bus", kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"])

    def test_mako_validation_accepts_timeout_after_successful_parse(self):
        def run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 2)

        with patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda name: "/bin/mako" if name == "mako" else None,
        ):
            try:
                self.manager.validate(run)
            except subprocess.TimeoutExpired as error:
                self.fail(f"bounded successful parse timeout was rejected: {error}")

    def test_real_mako_rejects_a_genuinely_malformed_config(self):
        mako = MODULE.shutil.which("mako")
        if mako is None:
            self.skipTest("mako is not installed")
        self.write(".config/mako/config", "this is not a mako option = [\n")

        with patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda name: mako if name == "mako" else None,
        ):
            with self.assertRaises(MODULE.IntegrationError):
                self.manager.validate(subprocess.run)

    def test_real_mako_accepts_valid_config_before_connection_failure(self):
        mako = MODULE.shutil.which("mako")
        if mako is None:
            self.skipTest("mako is not installed")
        self.write(
            ".config/mako/config",
            "background-color=#112233\ntext-color=#ffffff\n",
        )

        with patch.object(
            MODULE.shutil,
            "which",
            side_effect=lambda name: mako if name == "mako" else None,
        ):
            self.manager.validate(subprocess.run)

    def test_real_matugen_render_passes_niri_rofi_and_mako_validation(self):
        required_tools = ("matugen", "niri", "rofi", "mako")
        tools = {name: shutil.which(name) for name in required_tools}
        missing = [name for name, path in tools.items() if path is None]
        if missing:
            self.skipTest("missing real validators: " + ", ".join(missing))

        config_dir = self.home / ".config/matugen"
        shutil.copytree(ROOT / "matugen/templates", config_dir / "templates")
        shutil.copy2(ROOT / "matugen/config-niri.toml", config_dir / "config.toml")
        wallpaper = self.home / "wallpaper.png"
        wallpaper.parent.mkdir(parents=True, exist_ok=True)

        def png_chunk(kind, payload):
            body = kind + payload
            return (
                struct.pack(">I", len(payload))
                + body
                + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
            )

        wallpaper.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"\x00\x5f\x63\x68"))
            + png_chunk(b"IEND", b"")
        )
        environment = os.environ.copy()
        environment["HOME"] = str(self.home)
        environment["XDG_STATE_HOME"] = str(self.state)

        self.manager.begin()
        try:
            self.manager.deploy_static()
            rendered = subprocess.run(
                [
                    tools["matugen"],
                    "-c",
                    str(config_dir / "config.toml"),
                    "image",
                    str(wallpaper),
                    "--mode",
                    "dark",
                    "--source-color-index",
                    "0",
                    "-t",
                    "scheme-vibrant",
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            self.manager.activate()
            self.manager.validate(subprocess.run)
        finally:
            self.manager.rollback()

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
