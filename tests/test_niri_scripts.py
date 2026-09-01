import configparser
import json
import os
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "matugen-niri-apply"
WATCHER = ROOT / "bin" / "matugen-niri-watch"
NIRI_UNIT = ROOT / "systemd" / "matugen-niri.service"
REQUIRED_OUTPUTS = (
    ".config/niri/colors.kdl",
    ".config/waybar/colors.css",
    ".config/rofi/colors.rasi",
    ".config/mako/colors",
    ".config/gtk-3.0/gtk.css",
    ".config/gtk-3.0/colors.css",
    ".config/gtk-4.0/gtk.css",
    ".config/gtk-4.0/colors.css",
    ".config/kitty/themes/Matugen.conf",
    ".config/nvim/colors/matugen.vim",
    ".config/btop/themes/matugen.theme",
    ".config/cava/themes/matugen",
    ".config/tmux/generated.conf",
    ".config/zellij/themes/matugen.kdl",
    ".config/matugen/themes/starship-colors.toml",
    ".config/yazi/theme.toml",
    ".config/matugen/themes/obsidian.css",
)


class NiriApplyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.tools = self.base / "bin"
        self.tools.mkdir(parents=True)
        self.spaced = self.home / "Pictures/Wallpapers/a spaced name.png"
        self.second = self.home / "Pictures/Wallpapers/z-second.png"
        for image in (self.spaced, self.second):
            image.parent.mkdir(parents=True, exist_ok=True)
            image.touch()
        config_dir = self.home / ".config/matugen"
        (config_dir / "templates").mkdir(parents=True)
        (config_dir / "config.toml").touch()
        (config_dir / "templates/template.toml").touch()
        self.write_tool(
            "awww",
            """#!/usr/bin/env bash
if [[ "$1" == query && "${2:-}" == --all && "${3:-}" == --json ]]; then
  printf '%s' "${AWWW_JSON:-}"
  exit "${AWWW_JSON_STATUS:-0}"
fi
if [[ "$1" == query ]]; then
  printf '%s' "${AWWW_OUTPUT:-}"
  exit "${AWWW_STATUS:-0}"
fi
""",
        )
        self.write_tool(
            "swww",
            """#!/usr/bin/env bash
if [[ "$1" == query ]]; then
  printf '%s' "${SWWW_OUTPUT:-}"
  exit "${SWWW_STATUS:-0}"
fi
""",
        )

    def write_tool(self, name, source):
        path = self.tools / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    def run_script(self, *args, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.tools}{os.pathsep}{env['PATH']}",
                "XDG_RUNTIME_DIR": str(self.base / "runtime"),
            }
        )
        env.update({key: str(value) for key, value in overrides.items()})
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )


class NiriApplyResolverTests(NiriApplyTestCase):
    def run_query(self, awww_json=None, awww_stdout="", swww_stdout="", **overrides):
        daemon_env = {
            "AWWW_JSON": "" if awww_json is None else json.dumps(awww_json),
            "AWWW_OUTPUT": awww_stdout,
            "SWWW_OUTPUT": swww_stdout,
        }
        daemon_env.update(overrides)
        return self.run_script(
            "--print-wallpaper",
            **daemon_env,
        )

    def test_awww_json_preserves_spaces_and_sorts_outputs(self):
        payload = {
            "": [
                {"name": "HDMI-A-1", "displaying": {"image": str(self.second)}},
                {"name": "eDP-1", "displaying": {"image": str(self.spaced)}},
            ]
        }
        result = self.run_query(awww_json=payload)
        self.assertEqual(result.stdout.strip(), str(self.spaced))

    def test_invalid_awww_json_falls_back_to_swww_text(self):
        result = self.run_query(
            awww_json=None,
            awww_stdout="not-json",
            swww_stdout=f"eDP-1: image: {self.spaced}\n",
        )
        self.assertEqual(result.stdout.strip(), str(self.spaced))

    def test_legacy_awww_text_preserves_spaces(self):
        result = self.run_query(awww_stdout=f"eDP-1: path: {self.spaced}\n")
        self.assertEqual(result.stdout.strip(), str(self.spaced))

    def test_print_wallpaper_has_no_directory_fallback(self):
        result = self.run_query(awww_stdout="", swww_stdout="")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_print_wallpaper_ignores_explicit_argv_and_remains_daemon_only(self):
        payload = {
            "": [{"name": "eDP-1", "displaying": {"image": str(self.spaced)}}]
        }
        result = self.run_script(
            "--print-wallpaper",
            str(self.second),
            AWWW_JSON=json.dumps(payload),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{self.spaced}\n")

    def test_wallpaper_daemon_fallback_prefers_legacy_awww_before_swww(self):
        result = self.run_query(
            awww_stdout=f"eDP-1: image: {self.spaced}\n",
            swww_stdout=f"eDP-1: image: {self.second}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{self.spaced}\n")

    def test_failed_json_command_discards_its_valid_stdout(self):
        result = self.run_query(
            awww_json={"": [{"name": "eDP-1", "displaying": {"image": str(self.spaced)}}]},
            AWWW_JSON_STATUS=1,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_failed_legacy_command_discards_path_like_error_stdout(self):
        result = self.run_query(
            awww_stdout=f"eDP-1: image: {self.spaced}\n",
            swww_stdout=f"HDMI-A-1: path: {self.second}\n",
            AWWW_STATUS=1,
            SWWW_STATUS=1,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_failed_json_then_legacy_awww_prints_only_legacy_path(self):
        result = self.run_query(
            awww_json={"": [{"name": "HDMI-A-1", "displaying": {"image": str(self.second)}}]},
            awww_stdout=f"eDP-1: image: {self.spaced}\n",
            AWWW_JSON_STATUS=1,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"{self.spaced}\n")


class NiriApplyGenerationTests(NiriApplyTestCase):
    def setUp(self):
        super().setUp()
        self.args_file = self.base / "matugen-args.txt"
        self.write_tool(
            "matugen",
            """#!/usr/bin/env bash
printf '<%s>\\n' "$@" > "$MATUGEN_ARGS"
(( ${MATUGEN_STATUS:-0} == 0 )) || exit "$MATUGEN_STATUS"
while IFS= read -r output; do
  [[ -n "$output" ]] || continue
  [[ "$output" == "$MATUGEN_SKIP_OUTPUT" ]] && continue
  mkdir -p "$(dirname "$HOME/$output")"
  : > "$HOME/$output"
done <<< "$REQUIRED_OUTPUTS"
""",
        )

    def generation_env(self, skipped=""):
        return {
            "MATUGEN_ARGS": self.args_file,
            "MATUGEN_SKIP_OUTPUT": skipped,
            "MATUGEN_STATUS": "0",
            "REQUIRED_OUTPUTS": "\n".join(REQUIRED_OUTPUTS),
        }

    def test_explicit_wallpaper_with_spaces_is_one_matugen_argument_and_writes_state(self):
        result = self.run_script("manual", str(self.spaced), **self.generation_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"<{self.spaced}>\n", self.args_file.read_text(encoding="utf-8"))
        self.assertTrue((self.home / ".cache/matugen-niri/last-theme.txt").is_file())

    def test_missing_explicit_wallpaper_fails_before_running_matugen(self):
        missing = self.home / "Pictures/Wallpapers/missing.png"
        result = self.run_script("manual", str(missing), **self.generation_env())
        self.assertEqual(result.returncode, 1)
        self.assertIn("Wallpaper file not found", result.stdout)
        self.assertFalse(self.args_file.exists())

    def test_normal_apply_uses_daemon_wallpaper_before_directory_fallback(self):
        result = self.run_script(
            "manual",
            SWWW_OUTPUT=f"eDP-1: image: {self.second}\n",
            **self.generation_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"<{self.second}>\n", self.args_file.read_text(encoding="utf-8"))

    def test_matugen_nonzero_exit_does_not_write_theme_state(self):
        result = self.run_script(
            "manual",
            str(self.spaced),
            **(self.generation_env() | {"MATUGEN_STATUS": "9"}),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("matugen failed", result.stdout)
        self.assertFalse((self.home / ".cache/matugen-niri/last-theme.txt").exists())

    def test_missing_generated_niri_output_fails_without_writing_theme_state(self):
        result = self.run_script(
            "manual",
            str(self.spaced),
            **self.generation_env(skipped=".config/niri/colors.kdl"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.home / ".cache/matugen-niri/last-theme.txt").exists())

    def test_manual_apply_discards_failed_json_stdout_before_legacy_fallback(self):
        result = self.run_script(
            "manual",
            AWWW_JSON=json.dumps(
                {"": [{"name": "HDMI-A-1", "displaying": {"image": str(self.second)}}]}
            ),
            AWWW_JSON_STATUS=1,
            AWWW_OUTPUT=f"eDP-1: image: {self.spaced}\n",
            **self.generation_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"<{self.spaced}>\n", self.args_file.read_text(encoding="utf-8"))


class NiriWatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.tools = self.base / "bin"
        self.tools.mkdir(parents=True)
        self.calls = self.base / "apply-calls.txt"
        self.query_count = self.base / "query-count.txt"
        self.apply_count = self.base / "apply-count.txt"
        self.write_tool("pgrep", "#!/usr/bin/env bash\nexit \"${PGREP_STATUS:-0}\"\n")
        self.apply = self.write_tool(
            "fake-matugen-niri-apply",
            """#!/usr/bin/env bash
if [[ "${1:-}" == "--print-wallpaper" ]]; then
  count=0
  [[ -f "$MATUGEN_NIRI_QUERY_COUNT" ]] && count="$(<"$MATUGEN_NIRI_QUERY_COUNT")"
  (( count += 1 ))
  printf '%s\\n' "$count" > "$MATUGEN_NIRI_QUERY_COUNT"
  image="$(sed -n "${count}p" "$MATUGEN_NIRI_WATCH_SEQUENCE")"
  [[ "$image" == "__FAIL__" ]] && exit 1
  printf '%s\\n' "$image"
  exit 0
fi
printf '<%s>\\n' "$@" >> "$MATUGEN_NIRI_APPLY_CALLS"
count=0
[[ -f "$MATUGEN_NIRI_APPLY_COUNT" ]] && count="$(<"$MATUGEN_NIRI_APPLY_COUNT")"
(( count += 1 ))
printf '%s\\n' "$count" > "$MATUGEN_NIRI_APPLY_COUNT"
if (( count <= ${MATUGEN_NIRI_APPLY_FAILS:-0} )); then
  exit 1
fi
""",
        )

    def write_tool(self, name, source):
        path = self.tools / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    def run_watcher(self, sequence, polls, **overrides):
        sequence_file = self.base / "wallpaper-sequence.txt"
        sequence_file.write_text(sequence, encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.tools}{os.pathsep}{env['PATH']}",
                "WAYLAND_DISPLAY": "wayland-1",
                "MATUGEN_NIRI_APPLY": str(self.apply),
                "MATUGEN_NIRI_WATCH_INTERVAL": "0",
                "MATUGEN_NIRI_WATCH_MAX_POLLS": str(polls),
                "MATUGEN_NIRI_WATCH_SEQUENCE": str(sequence_file),
                "MATUGEN_NIRI_QUERY_COUNT": str(self.query_count),
                "MATUGEN_NIRI_APPLY_COUNT": str(self.apply_count),
                "MATUGEN_NIRI_APPLY_CALLS": str(self.calls),
            }
        )
        env.update({key: str(value) for key, value in overrides.items()})
        return subprocess.run(
            ["timeout", "3", "bash", str(WATCHER)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def call_lines(self):
        if not self.calls.exists():
            return []
        return self.calls.read_text(encoding="utf-8").splitlines()

    def test_applies_only_new_wallpapers_and_preserves_spaced_path(self):
        first = "/wallpapers/one with spaces.png"
        second = "/wallpapers/two.png"
        result = self.run_watcher(f"{first}\n{first}\n{second}\n", 3)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.call_lines(),
            ["<wallpaper>", f"<{first}>", "<wallpaper>", f"<{second}>"],
        )

    def test_failed_and_empty_queries_leave_last_applied_wallpaper_unchanged(self):
        first = "/wallpapers/one.png"
        result = self.run_watcher(f"{first}\n__FAIL__\n\n{first}\n", 4)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call_lines(), ["<wallpaper>", f"<{first}>"])

    def test_failed_apply_is_retried_for_the_same_wallpaper(self):
        image = "/wallpapers/one.png"
        result = self.run_watcher(
            f"{image}\n{image}\n",
            2,
            MATUGEN_NIRI_APPLY_FAILS=1,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.call_lines(),
            ["<wallpaper>", f"<{image}>", "<wallpaper>", f"<{image}>"],
        )

    def test_exits_without_sync_when_niri_is_not_running(self):
        result = self.run_watcher("/wallpapers/one.png\n", 1, PGREP_STATUS=1)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call_lines(), [])

    def test_missing_wayland_display_still_polls_the_wallpaper_daemon(self):
        result = self.run_watcher("\n\n", 2, WAYLAND_DISPLAY="")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.query_count.exists(), result.stderr)
        self.assertEqual(self.query_count.read_text(encoding="utf-8").strip(), "2")

    def test_service_path_reaches_user_bin_matugen_through_installed_helpers(self):
        parser = configparser.RawConfigParser(interpolation=None)
        parser.read(NIRI_UNIT, encoding="utf-8")
        environment = parser.get("Service", "Environment", fallback="")
        variables = dict(item.split("=", 1) for item in shlex.split(environment))
        path_template = variables.get("PATH")

        self.assertIsNotNone(path_template)
        self.assertIn("%h/.local/bin", path_template.split(":"))
        self.assertTrue({"/usr/local/bin", "/usr/bin", "/bin"}.issubset(path_template.split(":")))

        user_bin = self.home / ".local/bin"
        user_bin.mkdir(parents=True)
        for name, source in (
            ("matugen-niri-watch", WATCHER.read_text(encoding="utf-8")),
            ("matugen-niri-apply", SCRIPT.read_text(encoding="utf-8")),
            ("pgrep", "#!/usr/bin/env bash\nexit 0\n"),
            (
                "awww",
                "#!/usr/bin/env bash\nprintf '%s' \"$AWWW_JSON\"\n",
            ),
            (
                "matugen",
                """#!/usr/bin/env bash
printf '<%s>\\n' "$@" > "$MATUGEN_ARGS"
while IFS= read -r output; do
  [[ -n "$output" ]] || continue
  mkdir -p "$(dirname "$HOME/$output")"
  : > "$HOME/$output"
done <<< "$REQUIRED_OUTPUTS"
""",
            ),
        ):
            path = user_bin / name
            path.write_text(source, encoding="utf-8")
            path.chmod(0o755)

        image = self.home / "Pictures/daemon.png"
        image.parent.mkdir(parents=True)
        image.touch()
        config = self.home / ".config/matugen"
        (config / "templates").mkdir(parents=True)
        (config / "config.toml").touch()
        (config / "templates/template.toml").touch()
        args_file = self.base / "matugen-args.txt"
        path = ":".join(part.replace("%h", str(self.home)) for part in path_template.split(":"))
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": path,
                "MATUGEN_NIRI_WATCH_INTERVAL": "0",
                "MATUGEN_NIRI_WATCH_MAX_POLLS": "1",
                "AWWW_JSON": json.dumps(
                    {"": [{"name": "eDP-1", "displaying": {"image": str(image)}}]}
                ),
                "MATUGEN_ARGS": str(args_file),
                "REQUIRED_OUTPUTS": "\n".join(REQUIRED_OUTPUTS),
            }
        )
        result = subprocess.run(
            ["timeout", "3", str(user_bin / "matugen-niri-watch")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"<{image}>\n", args_file.read_text(encoding="utf-8"))

    def test_terminates_cleanly_when_signaled(self):
        sequence_file = self.base / "wallpaper-sequence.txt"
        sequence_file.write_text("\n", encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.tools}{os.pathsep}{env['PATH']}",
                "WAYLAND_DISPLAY": "wayland-1",
                "MATUGEN_NIRI_APPLY": str(self.apply),
                "MATUGEN_NIRI_WATCH_INTERVAL": "0.1",
                "MATUGEN_NIRI_WATCH_MAX_POLLS": "0",
                "MATUGEN_NIRI_WATCH_SEQUENCE": str(sequence_file),
                "MATUGEN_NIRI_QUERY_COUNT": str(self.query_count),
                "MATUGEN_NIRI_APPLY_COUNT": str(self.apply_count),
                "MATUGEN_NIRI_APPLY_CALLS": str(self.calls),
            }
        )
        process = subprocess.Popen(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(0.2)
            process.terminate()
            _, stderr = process.communicate(timeout=3)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

        self.assertEqual(process.returncode, 0, stderr)


if __name__ == "__main__":
    unittest.main()
