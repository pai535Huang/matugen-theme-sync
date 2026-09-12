import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "matugen-gnome-apply"

# What matugen writes for this run: positional colours plus the names
# Starship's default styles reference.
STARSHIP_COLORS = """[palettes.matugen]
color0 = '#fff8f5'
color3 = '#ffd8e4'
cyan = '#7d5260'
purple = '#625b71'
"""

# The shape of the real ~/.config/starship.toml: a stale third-party palette
# block sits next to the managed one, and the active palette is selected by a
# top-level key that must stay outside every table.
STARSHIP_CONF = """\"$schema\" = 'https://starship.rs/config-schema.json'
palette = "noctalia"

[azure]
symbol = "☁️ "

# BEGIN MATUGEN PALETTE
[palettes.matugen]
color0 = '#000000'
# END MATUGEN PALETTE

# >>> NOCTALIA STARSHIP PALETTE >>>
[palettes.noctalia]
cyan = "#b9cbbf"
# <<< NOCTALIA STARSHIP PALETTE <<<
"""

GSETTINGS = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$LOG_DIR/gsettings.log"
case "$1" in
  get)
    case "$2" in
      org.gnome.desktop.interface)
        printf "'%s'\\n" "${GSETTINGS_COLOR_SCHEME:-default}"
        ;;
    esac
    exit 0
    ;;
  list-schemas)
    exit 0
    ;;
  range)
    # Reported as unsupported: the accent-colour step then leaves the desktop
    # settings alone instead of reading generated GTK CSS.
    exit 1
    ;;
esac
exit 0
"""


class GnomeApplyTestCase(unittest.TestCase):
    """Runs the real apply script against a fake HOME and fake tools."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.tools = self.base / "bin"
        self.logs = self.base / "logs"
        for directory in (self.home, self.tools, self.logs):
            directory.mkdir(parents=True, exist_ok=True)

        self.wallpaper = self.home / "Pictures/wall.png"
        self.wallpaper.parent.mkdir(parents=True, exist_ok=True)
        self.wallpaper.write_bytes(b"\x89PNG\r\n\x1a\n")

        templates = self.home / ".config/matugen/templates"
        templates.mkdir(parents=True, exist_ok=True)
        (self.home / ".config/matugen/config.toml").write_text(
            "[config]\n", encoding="utf-8"
        )

        self.write_tool(
            "matugen",
            "#!/usr/bin/env bash\nset -e\n"
            'mkdir -p "$HOME/.config/matugen/themes"\n'
            "cat > \"$HOME/.config/matugen/themes/starship-colors.toml\" <<'EOF'\n"
            + STARSHIP_COLORS
            + "EOF\n",
        )
        self.write_tool("gsettings", GSETTINGS)
        self.write_tool("gnome-extensions", "#!/usr/bin/env bash\nexit 0\n")

        self.starship = self.home / ".config/starship.toml"
        self.starship.write_text(STARSHIP_CONF, encoding="utf-8")

    def write_tool(self, name, source):
        path = self.tools / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    def run_apply(self, *args, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.tools}{os.pathsep}{env['PATH']}",
                "LOG_DIR": str(self.logs),
                "DISPLAY": "",
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

    def read_starship(self):
        return self.starship.read_text(encoding="utf-8")

    def starship_config(self):
        return tomllib.loads(self.read_starship())

    def test_apply_selects_the_generated_palette(self):
        result = self.run_apply(str(self.wallpaper))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.starship_config()["palette"], "matugen")

    def test_generated_entries_replace_the_managed_block(self):
        result = self.run_apply(str(self.wallpaper))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.starship_config()["palettes"]["matugen"],
            {
                "color0": "#fff8f5",
                "color3": "#ffd8e4",
                "cyan": "#7d5260",
                "purple": "#625b71",
            },
        )

    def test_unrelated_keys_and_other_palettes_survive(self):
        result = self.run_apply(str(self.wallpaper))
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.starship_config()
        self.assertEqual(config["azure"]["symbol"], "☁️ ")
        self.assertEqual(config["palettes"]["noctalia"], {"cyan": "#b9cbbf"})

    def test_palette_key_precedes_the_first_table(self):
        result = self.run_apply(str(self.wallpaper))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.read_starship().splitlines()
        key_line = next(
            index for index, line in enumerate(lines) if re.match(r"^palette\s*=", line)
        )
        first_table = next(
            index for index, line in enumerate(lines) if line.startswith("[")
        )
        self.assertLess(key_line, first_table)


if __name__ == "__main__":
    unittest.main()
