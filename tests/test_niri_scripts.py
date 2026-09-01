import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "matugen-niri-apply"
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
fi
""",
        )
        self.write_tool(
            "swww",
            """#!/usr/bin/env bash
if [[ "$1" == query ]]; then
  printf '%s' "${SWWW_OUTPUT:-}"
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
    def run_query(self, awww_json=None, awww_stdout="", swww_stdout=""):
        return self.run_script(
            "--print-wallpaper",
            AWWW_JSON="" if awww_json is None else json.dumps(awww_json),
            AWWW_OUTPUT=awww_stdout,
            SWWW_OUTPUT=swww_stdout,
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


class NiriApplyGenerationTests(NiriApplyTestCase):
    def setUp(self):
        super().setUp()
        self.args_file = self.base / "matugen-args.txt"
        self.write_tool(
            "matugen",
            """#!/usr/bin/env bash
printf '<%s>\\n' "$@" > "$MATUGEN_ARGS"
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
            "REQUIRED_OUTPUTS": "\n".join(REQUIRED_OUTPUTS),
        }

    def test_explicit_wallpaper_with_spaces_is_one_matugen_argument_and_writes_state(self):
        result = self.run_script("manual", str(self.spaced), **self.generation_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"<{self.spaced}>\n", self.args_file.read_text(encoding="utf-8"))
        self.assertTrue((self.home / ".cache/matugen-niri/last-theme.txt").is_file())

    def test_missing_generated_niri_output_fails_without_writing_theme_state(self):
        result = self.run_script(
            "manual",
            str(self.spaced),
            **self.generation_env(skipped=".config/niri/colors.kdl"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.home / ".cache/matugen-niri/last-theme.txt").exists())


if __name__ == "__main__":
    unittest.main()
