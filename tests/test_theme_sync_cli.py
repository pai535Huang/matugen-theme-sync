import contextlib
import importlib.machinery
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))
LOADER = importlib.machinery.SourceFileLoader(
    "matugen_theme_sync_cli", str(BIN / "matugen-theme-sync")
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class DesktopDetectionTests(unittest.TestCase):
    def test_niri_socket_wins_over_mixed_desktop_hints(self):
        with mock.patch.dict(
            MODULE.os.environ,
            {
                "NIRI_SOCKET": "/run/user/1000/niri.sock",
                "XDG_CURRENT_DESKTOP": "niri:GNOME",
            },
            clear=True,
        ):
            self.assertEqual(MODULE.detect_desktop(), MODULE.DE_NIRI)

    def test_installed_executable_does_not_claim_inactive_desktop(self):
        with mock.patch.dict(
            MODULE.os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True
        ), mock.patch.object(
            MODULE.shutil, "which", return_value="/usr/bin/niri"
        ):
            self.assertIsNone(MODULE.detect_desktop())

    def test_existing_plasma_and_gnome_session_hints_still_detect(self):
        for hint, expected in (
            ("KDE", MODULE.DE_PLASMA),
            ("GNOME", MODULE.DE_GNOME),
        ):
            with self.subTest(hint=hint), mock.patch.dict(
                MODULE.os.environ, {"XDG_CURRENT_DESKTOP": hint}, clear=True
            ):
                self.assertEqual(MODULE.detect_desktop(), expected)

    def test_niri_dependency_report_accepts_awww_only(self):
        available = {
            "matugen": "/bin/matugen",
            "niri": "/bin/niri",
            "awww": "/bin/awww",
        }
        with mock.patch.object(
            MODULE.shutil, "which", side_effect=available.get
        ):
            required, optional = MODULE.dependency_report(MODULE.DE_NIRI)
        self.assertEqual(required, [])
        self.assertEqual(optional, ["makoctl", "waybar", "rofi"])

    def test_niri_dependency_report_accepts_legacy_swww_only(self):
        available = {
            "matugen": "/bin/matugen",
            "niri": "/bin/niri",
            "swww": "/bin/swww",
        }
        with mock.patch.object(MODULE.shutil, "which", side_effect=available.get):
            required, optional = MODULE.dependency_report(MODULE.DE_NIRI)
        self.assertEqual(required, [])
        self.assertEqual(optional, ["makoctl", "waybar", "rofi"])

    def test_niri_dependency_report_requires_one_wallpaper_daemon(self):
        available = {"matugen": "/bin/matugen", "niri": "/bin/niri"}
        with mock.patch.object(MODULE.shutil, "which", side_effect=available.get):
            required, optional = MODULE.dependency_report(MODULE.DE_NIRI)
        self.assertEqual(required, ["swww/awww"])
        self.assertEqual(optional, ["makoctl", "waybar", "rofi"])

    def test_each_desktop_reports_each_missing_required_dependency(self):
        all_tools = {
            "matugen": "/bin/matugen",
            "kreadconfig6": "/bin/kreadconfig6",
            "kwriteconfig6": "/bin/kwriteconfig6",
            "plasma-apply-colorscheme": "/bin/plasma-apply-colorscheme",
            "gsettings": "/bin/gsettings",
            "niri": "/bin/niri",
            "awww": "/bin/awww",
            "swww": "/bin/swww",
            "makoctl": "/bin/makoctl",
            "waybar": "/bin/waybar",
            "rofi": "/bin/rofi",
        }
        cases = (
            (MODULE.DE_PLASMA, {"kreadconfig6"}, {"kreadconfig6"}),
            (MODULE.DE_PLASMA, {"kwriteconfig6"}, {"kwriteconfig6"}),
            (
                MODULE.DE_PLASMA,
                {"plasma-apply-colorscheme"},
                {"plasma-apply-colorscheme"},
            ),
            (MODULE.DE_GNOME, {"gsettings"}, {"gsettings"}),
            (MODULE.DE_NIRI, {"niri"}, {"niri"}),
            (MODULE.DE_NIRI, {"awww", "swww"}, {"swww/awww"}),
        )
        for desktop, missing, expected in cases:
            with self.subTest(desktop=desktop, missing=missing):
                available = {
                    tool: path for tool, path in all_tools.items() if tool not in missing
                }
                with mock.patch.object(
                    MODULE.shutil, "which", side_effect=available.get
                ):
                    required, optional = MODULE.dependency_report(desktop)
                self.assertSetEqual(set(required), expected)
                self.assertEqual(optional, [])

    def test_dependency_output_reports_optional_apps_separately(self):
        output = io.StringIO()
        with mock.patch.object(
            MODULE,
            "dependency_report",
            return_value=(["matugen"], ["waybar"]),
        ), contextlib.redirect_stdout(output):
            result = MODULE.check_dependencies(MODULE.DE_NIRI)
        self.assertFalse(result)
        self.assertIn("缺少依赖: matugen", output.getvalue())
        self.assertIn("未安装可选组件: waybar", output.getvalue())


class FakeNiriIntegration:
    calls = None
    root = None
    failures = None
    commit_warning = None

    def __init__(self, home, state_home, resources):
        self.home = home
        self.state_home = state_home
        self.resources = resources
        self.root = type(self).root or Path(state_home) / "matugen-theme-sync/niri"

    def record(self, method):
        self.calls.append(method)
        failure = self.failures.get(method)
        if failure is not None:
            raise failure

    def begin(self):
        self.record("begin")

    def deploy_static(self):
        self.record("deploy_static")

    def activate(self):
        self.record("activate")

    def validate(self, run):
        self.record("validate")

    def reload(self, run):
        self.record("reload")
        return []

    def commit(self):
        self.record("commit")
        return self.commit_warning

    def rollback(self):
        self.record("rollback")

    def restore(self):
        self.calls.append("restore")


class NiriCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.resources = self.base / "resources"
        self.bin_dir = self.resources / "bin"
        self.matugen_dir = self.resources / "matugen"
        self.templates_dir = self.matugen_dir / "templates"
        self.systemd_dir = self.resources / "systemd"
        self.niri_resources = self.resources / "niri"
        for directory in (
            self.bin_dir,
            self.templates_dir,
            self.systemd_dir,
            self.niri_resources,
        ):
            directory.mkdir(parents=True)
        for script in MODULE.DE_INFO[MODULE.DE_NIRI]["scripts"]:
            (self.bin_dir / script).write_text("#!/bin/sh\n", encoding="utf-8")
        (self.matugen_dir / "config-niri.toml").write_text(
            "[config]\n", encoding="utf-8"
        )
        (self.templates_dir / "colors.txt").write_text(
            "template\n", encoding="utf-8"
        )
        (self.systemd_dir / "matugen-niri.service").write_text(
            "[Service]\n", encoding="utf-8"
        )
        for relative, content in (
            ("waybar/style.css", '@import url("@MATUGEN_WAYBAR_COLORS@");\n'),
            ("rofi/matugen.rasi", '@import "../colors.rasi"\n'),
            ("mako/config", "include=@MATUGEN_MAKO_COLORS@\n"),
        ):
            target = self.niri_resources / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.calls = []
        FakeNiriIntegration.calls = self.calls
        FakeNiriIntegration.root = None
        FakeNiriIntegration.failures = {}
        FakeNiriIntegration.commit_warning = None
        self.constant_patches = mock.patch.multiple(
            MODULE,
            HOME=self.home,
            LOCAL_BIN=self.home / ".local/bin",
            MATUGEN_CONFIG_DIR=self.home / ".config/matugen",
            SYSTEMD_USER_DIR=self.home / ".config/systemd/user",
            BIN_DIR=self.bin_dir,
            MATUGEN_DIR=self.matugen_dir,
            TEMPLATES_DIR=self.templates_dir,
            SYSTEMD_DIR=self.systemd_dir,
            NIRI_RESOURCES_DIR=self.niri_resources,
        )
        self.constant_patches.start()
        self.addCleanup(self.constant_patches.stop)
        self.environment = mock.patch.dict(
            MODULE.os.environ,
            {
                "HOME": str(self.home),
                "PATH": str(self.home / ".local/bin"),
                "XDG_STATE_HOME": str(self.home / ".local/state"),
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_apply(
        self,
        *,
        bootstrap_enabled=True,
        bootstrap_result=0,
        service_result=True,
        service_exception=None,
        disable_exception=None,
    ):
        def bootstrap_call(command):
            self.calls.append("bootstrap")
            return bootstrap_result

        def enable(info_de, start):
            self.calls.append("enable_service")
            self.assertTrue(start)
            if service_exception is not None:
                raise service_exception
            return service_result

        def disable(info_de):
            self.calls.append("disable_service")
            if disable_exception is not None:
                raise disable_exception

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(MODULE, "NiriIntegration", FakeNiriIntegration)
            )
            stack.enter_context(
                mock.patch.object(MODULE, "stream", side_effect=bootstrap_call)
            )
            stack.enter_context(
                mock.patch.object(MODULE, "install_service", side_effect=enable)
            )
            stack.enter_context(
                mock.patch.object(MODULE, "disable_service", side_effect=disable)
            )
            stack.enter_context(mock.patch.object(MODULE, "check_dependencies"))
            stack.enter_context(
                mock.patch.object(
                    MODULE, "detect_session_type", return_value="wayland"
                )
            )
            stack.enter_context(
                mock.patch.object(
                    MODULE,
                    "script_path",
                    return_value=BIN / "matugen-theme-sync",
                )
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    result = MODULE.cmd_apply(
                        force_de=MODULE.DE_NIRI, bootstrap=bootstrap_enabled
                    )
                except Exception as exc:
                    self.fail(f"cmd_apply leaked an exception: {exc}")
            self.apply_output = output.getvalue()
            return result

    def test_niri_apply_runs_transaction_in_exact_order(self):
        result = self.run_apply()
        self.assertEqual(result, 0)
        self.assertEqual(
            self.calls,
            [
                "begin",
                "deploy_static",
                "bootstrap",
                "activate",
                "validate",
                "reload",
                "enable_service",
                "commit",
            ],
        )

    def test_failed_bootstrap_rolls_back_before_activation(self):
        result = self.run_apply(bootstrap_result=1)
        self.assertEqual(result, 1)
        self.assertEqual(
            self.calls, ["begin", "deploy_static", "bootstrap", "rollback"]
        )

    def test_failed_service_attempt_disables_then_rolls_back(self):
        result = self.run_apply(service_result=False)
        self.assertEqual(result, 1)
        self.assertEqual(
            self.calls[-3:], ["enable_service", "disable_service", "rollback"]
        )

    def test_begin_failure_returns_original_error_without_rollback(self):
        FakeNiriIntegration.failures["begin"] = MODULE.IntegrationError(
            "unsafe target"
        )

        result = self.run_apply()

        self.assertEqual(result, 1)
        self.assertEqual(self.calls, ["begin"])
        self.assertIn("unsafe target", self.apply_output)

    def test_pre_service_stage_failures_only_rollback_started_transaction(self):
        cases = (
            ("deploy_static", ["begin", "deploy_static", "rollback"]),
            (
                "activate",
                ["begin", "deploy_static", "bootstrap", "activate", "rollback"],
            ),
            (
                "validate",
                [
                    "begin",
                    "deploy_static",
                    "bootstrap",
                    "activate",
                    "validate",
                    "rollback",
                ],
            ),
            (
                "reload",
                [
                    "begin",
                    "deploy_static",
                    "bootstrap",
                    "activate",
                    "validate",
                    "reload",
                    "rollback",
                ],
            ),
        )
        for method, expected in cases:
            with self.subTest(method=method):
                self.calls.clear()
                FakeNiriIntegration.failures = {
                    method: MODULE.IntegrationError(f"{method} failed")
                }
                result = self.run_apply()
                self.assertEqual(result, 1)
                self.assertEqual(self.calls, expected)
                self.assertIn(f"{method} failed", self.apply_output)

    def test_service_exception_disables_then_rolls_back(self):
        result = self.run_apply(service_exception=OSError("systemd unavailable"))

        self.assertEqual(result, 1)
        self.assertEqual(
            self.calls[-3:], ["enable_service", "disable_service", "rollback"]
        )
        self.assertIn("systemd unavailable", self.apply_output)

    def test_pre_journal_commit_failure_disables_then_rolls_back(self):
        FakeNiriIntegration.failures["commit"] = OSError("journal write failed")

        result = self.run_apply()

        self.assertEqual(result, 1)
        self.assertEqual(
            self.calls[-3:], ["commit", "disable_service", "rollback"]
        )
        self.assertIn("journal write failed", self.apply_output)

    def test_cleanup_failures_do_not_mask_business_error_or_each_other(self):
        FakeNiriIntegration.failures["commit"] = OSError("journal write failed")
        FakeNiriIntegration.failures["rollback"] = OSError("rollback cleanup failed")

        result = self.run_apply(disable_exception=OSError("disable cleanup failed"))

        self.assertEqual(result, 1)
        self.assertEqual(
            self.calls[-3:], ["commit", "disable_service", "rollback"]
        )
        self.assertIn("journal write failed", self.apply_output)
        self.assertIn("disable cleanup failed", self.apply_output)
        self.assertIn("rollback cleanup failed", self.apply_output)
        self.assertLess(
            self.apply_output.index("journal write failed"),
            self.apply_output.index("disable cleanup failed"),
        )

    def test_durable_pending_error_keeps_service_and_does_not_rollback(self):
        class TestDurableCommitError(OSError):
            pass

        FakeNiriIntegration.failures["commit"] = TestDurableCommitError(
            "durable commit pending recovery"
        )
        with mock.patch.object(
            MODULE, "DurableCommitError", TestDurableCommitError, create=True
        ):
            result = self.run_apply()

        self.assertEqual(result, 1)
        self.assertEqual(self.calls[-2:], ["enable_service", "commit"])
        self.assertIn("durable commit pending recovery", self.apply_output)

    def test_real_post_journal_recovery_keeps_service_and_returns_success(self):
        manager = MODULE.NiriIntegration(
            self.home,
            self.home / ".local/state",
            self.niri_resources,
        )
        real_replace = MODULE.os.replace
        failed_once = False

        def fail_manifest_once(source, destination):
            nonlocal failed_once
            if (
                Path(destination) == manager.manifest_path
                and manager.committed_manifest_path.is_file()
                and not failed_once
            ):
                failed_once = True
                raise OSError("injected manifest failure")
            return real_replace(source, destination)

        def enable(info_de, start):
            self.calls.append("enable_service")
            return True

        output = io.StringIO()
        integration_module = sys.modules[MODULE.NiriIntegration.__module__]
        with mock.patch.object(
            MODULE, "NiriIntegration", return_value=manager
        ), mock.patch.object(
            MODULE, "stream", return_value=0
        ), mock.patch.object(
            MODULE, "install_service", side_effect=enable
        ), mock.patch.object(
            MODULE,
            "disable_service",
            side_effect=AssertionError("durable deployment service was disabled"),
        ), mock.patch.object(
            MODULE, "check_dependencies"
        ), mock.patch.object(
            MODULE, "detect_session_type", return_value="wayland"
        ), mock.patch.object(
            MODULE, "script_path", return_value=BIN / "matugen-theme-sync"
        ), mock.patch.object(
            integration_module.shutil, "which", return_value=None
        ), mock.patch.object(
            MODULE.os, "replace", side_effect=fail_manifest_once
        ), contextlib.redirect_stdout(output):
            result = MODULE.cmd_apply(force_de=MODULE.DE_NIRI)

        self.assertEqual(result, 0)
        self.assertEqual(self.calls, ["enable_service"])
        self.assertIn("durable", output.getvalue())
        self.assertTrue(manager.manifest_path.is_file())
        self.assertFalse(manager.committed_manifest_path.exists())
        self.assertFalse(manager.transaction.exists())

    def test_no_bootstrap_only_installs_supporting_files(self):
        output = io.StringIO()
        with mock.patch.object(
            MODULE, "NiriIntegration", side_effect=AssertionError("transaction started")
        ), mock.patch.object(
            MODULE, "install_service", side_effect=AssertionError("service enabled")
        ), mock.patch.object(
            MODULE, "check_dependencies"
        ), mock.patch.object(
            MODULE, "detect_session_type", return_value="wayland"
        ), mock.patch.object(
            MODULE, "script_path", return_value=BIN / "matugen-theme-sync"
        ), contextlib.redirect_stdout(output):
            result = MODULE.cmd_apply(force_de=MODULE.DE_NIRI, bootstrap=False)

        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(
            (self.home / ".config/systemd/user/matugen-niri.service").is_file()
        )
        self.assertTrue((self.home / ".config/matugen/config.toml").is_file())
        self.assertTrue(
            (self.home / ".config/matugen/templates/colors.txt").is_file()
        )
        self.assertFalse((self.home / ".config/niri/config.kdl").exists())
        self.assertIn("--no-bootstrap", output.getvalue())

    def test_niri_uninstall_disables_restores_then_removes_helpers(self):
        local_bin = self.home / ".local/bin"
        local_bin.mkdir(parents=True)
        for script in MODULE.DE_INFO[MODULE.DE_NIRI]["scripts"]:
            (local_bin / script).write_text("helper\n", encoding="utf-8")

        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name in MODULE.DE_INFO[MODULE.DE_NIRI]["scripts"]:
                self.calls.append("remove_helper")
            return original_unlink(path, *args, **kwargs)

        def disable(info_de):
            self.calls.append("disable_service")

        with mock.patch.object(
            MODULE, "NiriIntegration", FakeNiriIntegration
        ), mock.patch.object(
            MODULE, "disable_service", side_effect=disable
        ), mock.patch.object(
            MODULE, "detect_session_type", return_value="wayland"
        ), mock.patch.object(Path, "unlink", unlink), contextlib.redirect_stdout(
            io.StringIO()
        ):
            result = MODULE.cmd_uninstall(force_de=MODULE.DE_NIRI)

        self.assertEqual(result, 0)
        self.assertEqual(
            self.calls,
            ["disable_service", "restore", "remove_helper", "remove_helper"],
        )

    def test_purge_preserves_nonempty_conflict_archive_and_reports_path(self):
        state_root = self.home / ".local/state/matugen-theme-sync/niri"
        conflict = state_root / "conflicts/20260902T010203/waybar-style"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("user edit\n", encoding="utf-8")
        FakeNiriIntegration.root = state_root
        config = self.home / ".config/matugen/config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("[config]\n", encoding="utf-8")
        cache = self.home / ".cache/matugen-niri/last-theme.txt"
        cache.parent.mkdir(parents=True)
        cache.write_text("state\n", encoding="utf-8")
        output = io.StringIO()

        with mock.patch.object(
            MODULE, "NiriIntegration", FakeNiriIntegration
        ), mock.patch.object(MODULE, "disable_service"), mock.patch.object(
            MODULE, "detect_session_type", return_value="wayland"
        ), contextlib.redirect_stdout(output):
            result = MODULE.cmd_uninstall(force_de=MODULE.DE_NIRI, purge=True)

        self.assertEqual(result, 0)
        self.assertTrue(conflict.is_file())
        self.assertFalse(config.exists())
        self.assertFalse(cache.exists())
        self.assertIn(str(state_root / "conflicts"), output.getvalue())


if __name__ == "__main__":
    unittest.main()
