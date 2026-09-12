import os
import re
import shlex
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "matugen-plasma-apply"

# Mirrors the output list matugen-plasma-apply verifies after generation.
REQUIRED_OUTPUTS = (
    ".config/gtk-3.0/gtk.css",
    ".config/gtk-3.0/colors.css",
    ".config/gtk-4.0/gtk.css",
    ".config/gtk-4.0/colors.css",
    ".themes/Matugen/gnome-shell/gnome-shell.css",
    ".config/kitty/themes/Matugen.conf",
    ".config/nvim/colors/matugen.vim",
    ".config/btop/themes/matugen.theme",
    ".config/cava/themes/matugen",
    ".config/tmux/generated.conf",
    ".config/zellij/themes/matugen.kdl",
    ".config/matugen/themes/starship-colors.toml",
    ".config/yazi/theme.toml",
    ".config/matugen/themes/obsidian.css",
    ".config/qt5ct/colors/matugen.conf",
    ".config/qt6ct/colors/matugen.conf",
    ".local/share/color-schemes/MatugenLight.colors",
    ".local/share/color-schemes/MatugenDark.colors",
)

KITTY_THEME = """# --- Main Colors ---
background            #fff8f5
foreground            #231a13
cursor                #231a13
color0                #fff8f5
color1                #ba1a1a
"""

# What themes/Matugen.conf and current-theme.conf hold before this run: the
# previous (dark) generation.
OLD_KITTY_THEME = """# --- Main Colors ---
background            #121412
foreground            #e2e3df
"""

KITTY_CONF = """font_size 11.0
include themes/noctalia.conf

# BEGIN_KITTY_THEME
# Matugen
include current-theme.conf
# END_KITTY_THEME
"""

# Trimmed copies of the real files on this machine, including unrelated keys
# that must survive untouched.
GTK3_SETTINGS = """[Settings]
gtk-application-prefer-dark-theme=true
gtk-button-images=true
gtk-cursor-theme-name=breeze_cursors
gtk-font-name=Adwaita Sans,  11
gtk-icon-theme-name=breeze
gtk-theme-name=adw-gtk3
gtk-toolbar-style=3
"""

GTK4_SETTINGS = """[Settings]
gtk-application-prefer-dark-theme=true
gtk-cursor-theme-name=breeze_cursors
gtk-icon-theme-name=breeze
gtk-theme-name=adw-gtk3
"""

XSETTINGSD = """Gdk/WindowScalingFactor 2
Gtk/CursorThemeSize 24
Gtk/FontName "Adwaita Sans,  11"
Net/IconThemeName "breeze"
Net/ThemeName "adw-gtk3"
"""

# What matugen writes for this run: positional colours plus the names
# Starship's default styles reference.
STARSHIP_COLORS = """[palettes.matugen]
color0 = '#fdf8fb'
color3 = '#1f1637'
cyan = '#ba1a1a'
purple = '#615c6c'
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
color3 = '#111111'
cyan = '#222222'
# END MATUGEN PALETTE

# >>> NOCTALIA STARSHIP PALETTE >>>
[palettes.noctalia]
cyan = "#b9cbbf"
# <<< NOCTALIA STARSHIP PALETTE <<<
"""

STARSHIP_CONF_WITHOUT_PALETTE_KEY = STARSHIP_CONF.replace(
    'palette = "noctalia"\n', "", 1
)


def parse_ini(text):
    """Return {key: value} for the flattened settings.ini body."""
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip()
    return settings


def parse_xsettingsd(text):
    """Return {key: value} for xsettingsd.conf, strings unquoted."""
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        settings[key] = value
    return settings


class PlasmaApplyTestCase(unittest.TestCase):
    """Runs the real apply script against a fake HOME and fake tools."""

    pgrep_match = "kitty,xsettingsd"
    make_gtk_settings = True
    make_xsettingsd = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.tools = self.base / "bin"
        self.logs = self.base / "logs"
        self.runtime = self.base / "runtime"
        for directory in (self.home, self.tools, self.logs, self.runtime):
            directory.mkdir(parents=True, exist_ok=True)
        # session_shutting_down treats a missing compositor socket as shutdown.
        (self.runtime / "wayland-0").touch()

        self.wallpaper = self.home / "Pictures/Wallpapers/wall.png"
        self.wallpaper.parent.mkdir(parents=True, exist_ok=True)
        self.wallpaper.write_bytes(b"\x89PNG\r\n\x1a\n")

        matugen_dir = self.home / ".config/matugen"
        (matugen_dir / "templates").mkdir(parents=True, exist_ok=True)
        (matugen_dir / "config.toml").write_text("[config]\n", encoding="utf-8")
        (matugen_dir / "templates/template.toml").write_text(
            "[templates.x]\n", encoding="utf-8"
        )

        (self.home / ".config/kitty/themes").mkdir(parents=True, exist_ok=True)
        self.kitty_theme = self.home / ".config/kitty/themes/Matugen.conf"
        self.kitty_theme.write_text(OLD_KITTY_THEME, encoding="utf-8")
        self.kitty_conf = self.home / ".config/kitty/kitty.conf"
        self.kitty_conf.write_text(KITTY_CONF, encoding="utf-8")
        self.kitty_current = self.home / ".config/kitty/current-theme.conf"
        self.kitty_current.write_text(OLD_KITTY_THEME, encoding="utf-8")

        if self.make_gtk_settings:
            (self.home / ".config/gtk-3.0").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/gtk-4.0").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/gtk-3.0/settings.ini").write_text(
                GTK3_SETTINGS, encoding="utf-8"
            )
            (self.home / ".config/gtk-4.0/settings.ini").write_text(
                GTK4_SETTINGS, encoding="utf-8"
            )
        if self.make_xsettingsd:
            (self.home / ".config/xsettingsd").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/xsettingsd/xsettingsd.conf").write_text(
                XSETTINGSD, encoding="utf-8"
            )

        self.write_appletsrc()
        self.write_tools()

    def write_appletsrc(self):
        (self.home / ".config").mkdir(parents=True, exist_ok=True)
        (self.home / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
            "[Containments][1]\n"
            "plugin=org.kde.desktopcontainment\n"
            "wallpaperplugin=org.kde.image\n"
            "\n"
            "[Containments][1][Wallpaper][org.kde.image][General]\n"
            f"Image=file://{self.wallpaper}\n",
            encoding="utf-8",
        )

    def write_tool(self, name, source):
        path = self.tools / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    def write_tools(self):
        outputs = "\n".join(
            f'mkdir -p "$HOME/{os.path.dirname(item)}"; : > "$HOME/{item}"'
            for item in REQUIRED_OUTPUTS
        )
        self.write_tool(
            "matugen",
            "#!/usr/bin/env bash\nset -e\n"
            + outputs
            + "\nprintf '%s' "
            + shlex.quote(KITTY_THEME)
            + ' > "$HOME/.config/kitty/themes/Matugen.conf"\n'
            + "printf '%s' "
            + shlex.quote(STARSHIP_COLORS)
            + ' > "$HOME/.config/matugen/themes/starship-colors.toml"\n'
            + "exit 0\n",
        )
        self.write_tool(
            "kreadconfig6",
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "${KREADCONFIG_SCHEME:-MatugenLight}"\n',
        )
        self.write_tool(
            "pgrep",
            "#!/usr/bin/env bash\n"
            'name="$2"\n'
            'if [[ ",${PGREP_MATCH:-}," == *",$name,"* ]]; then exit 0; fi\n'
            "exit 1\n",
        )
        self.write_tool(
            "pkill",
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >> "$LOG_DIR/pkill.log"\n'
            'exit "${PKILL_STATUS:-0}"\n',
        )
        # Any kitten/theme-database call must be visible: the reload path is
        # not allowed to depend on the network.
        self.write_tool(
            "kitty",
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >> "$LOG_DIR/kitty.log"\n'
            "exit 0\n",
        )
        self.write_tool(
            "gsettings",
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "$*" >> "$LOG_DIR/gsettings.log"\n'
            "exit 0\n",
        )
        self.write_tool(
            "kwriteconfig6",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        self.write_tool(
            "plasma-apply-colorscheme",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        # Never touch a live tmux server from the test suite.
        self.write_tool("tmux", "#!/usr/bin/env bash\nexit 1\n")

    def run_apply(self, *args, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.tools}{os.pathsep}{env['PATH']}",
                "XDG_RUNTIME_DIR": str(self.runtime),
                "LOG_DIR": str(self.logs),
                "PGREP_MATCH": self.pgrep_match,
                "WAYLAND_DISPLAY": "wayland-0",
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

    def apply_light(self, **overrides):
        overrides.setdefault("KREADCONFIG_SCHEME", "MatugenLight")
        return self.run_apply("light", "manual", **overrides)

    def apply_dark(self, **overrides):
        overrides.setdefault("KREADCONFIG_SCHEME", "MatugenDark")
        return self.run_apply("dark", "manual", **overrides)

    def read_log(self, name):
        path = self.logs / f"{name}.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def settings_ini(self, version=3):
        return self.home / f".config/gtk-{version}.0/settings.ini"

    def read_settings(self, version=3):
        return parse_ini(self.settings_ini(version).read_text(encoding="utf-8"))

    def read_xsettingsd(self):
        return parse_xsettingsd(
            (self.home / ".config/xsettingsd/xsettingsd.conf").read_text(
                encoding="utf-8"
            )
        )


class KittyReloadTests(PlasmaApplyTestCase):
    def test_reload_materializes_theme_and_signals_without_kitten(self):
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.kitty_current.read_text(encoding="utf-8"), KITTY_THEME)
        self.assertEqual(self.read_log("kitty"), "")
        self.assertIn("SIGUSR1", self.read_log("pkill"))
        self.assertIn("kitty", self.read_log("pkill"))

    def test_reload_skips_signal_when_kitty_is_not_running(self):
        result = self.apply_light(PGREP_MATCH="")
        self.assertEqual(result.returncode, 0, result.stderr)
        # The theme file is persisted for the next launch, but nothing is signalled.
        self.assertEqual(self.kitty_current.read_text(encoding="utf-8"), KITTY_THEME)
        self.assertNotIn("kitty", self.read_log("pkill"))
        self.assertIn("kitty is not running", result.stdout)

    def test_reload_failure_is_reported_and_fails_the_run(self):
        result = self.apply_light(PKILL_STATUS=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not signal kitty", result.stdout)
        self.assertIn("live synchronization steps failed", result.stdout)

    def test_reload_write_failure_is_reported_and_fails_the_run(self):
        # Occupy the temporary path used for the atomic replace, so the theme
        # file cannot be materialised (a full/unwritable config dir behaves
        # the same way).
        (self.home / ".config/kitty/current-theme.conf.tmp").mkdir()
        result = self.apply_light()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not write kitty theme file", result.stdout)

    def test_reload_warns_when_kitty_conf_does_not_include_the_theme(self):
        self.kitty_conf.write_text("font_size 11.0\n", encoding="utf-8")
        result = self.apply_light()
        self.assertIn("current-theme.conf", result.stdout)
        self.assertIn("include", result.stdout)


class GtkModeTests(PlasmaApplyTestCase):
    def test_light_mode_switches_both_settings_ini_files(self):
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        for version in (3, 4):
            with self.subTest(gtk=version):
                settings = self.read_settings(version)
                self.assertEqual(settings["gtk-application-prefer-dark-theme"], "false")
                self.assertEqual(settings["gtk-theme-name"], "adw-gtk3")

    def test_dark_mode_switches_both_settings_ini_files(self):
        result = self.apply_dark()
        self.assertEqual(result.returncode, 0, result.stderr)
        for version in (3, 4):
            with self.subTest(gtk=version):
                settings = self.read_settings(version)
                self.assertEqual(settings["gtk-application-prefer-dark-theme"], "true")
                self.assertEqual(settings["gtk-theme-name"], "adw-gtk3-dark")

    def test_unrelated_settings_ini_keys_are_preserved(self):
        self.apply_light()
        after = self.read_settings(3)
        self.assertEqual(after["gtk-application-prefer-dark-theme"], "false")
        self.assertEqual(after["gtk-theme-name"], "adw-gtk3")
        before = parse_ini(GTK3_SETTINGS)
        before.pop("gtk-application-prefer-dark-theme")
        before.pop("gtk-theme-name")
        after.pop("gtk-application-prefer-dark-theme")
        after.pop("gtk-theme-name")
        self.assertEqual(after, before)

    def test_settings_ini_is_created_when_missing(self):
        for version in (3, 4):
            self.settings_ini(version).unlink()
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        for version in (3, 4):
            with self.subTest(gtk=version):
                settings = self.read_settings(version)
                self.assertEqual(settings["gtk-application-prefer-dark-theme"], "false")
                self.assertEqual(settings["gtk-theme-name"], "adw-gtk3")

    def test_keys_land_in_settings_group_when_header_is_absent(self):
        # A key appended outside [Settings] is read by nobody, which is the
        # silent no-op this mode is supposed to avoid.
        self.settings_ini(3).write_text("gtk-button-images=true\n", encoding="utf-8")
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.settings_ini(3).read_text(encoding="utf-8")
        self.assertIn("[Settings]", text)
        lines = [
            line.strip() for line in text.splitlines() if line.strip().startswith("gtk-")
        ]
        header = text.splitlines().index("[Settings]")
        for index, line in enumerate(text.splitlines()):
            if line.strip().startswith("gtk-"):
                self.assertGreater(index, header, line)
        self.assertTrue(lines)

    def test_xsettingsd_theme_name_is_kept_in_sync_and_reloaded(self):
        result = self.apply_dark()
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = self.read_xsettingsd()
        self.assertEqual(settings["Net/ThemeName"], "adw-gtk3-dark")
        self.assertEqual(settings["Gtk/ApplicationPreferDarkTheme"], "1")
        self.assertEqual(settings["Gtk/CursorThemeSize"], "24")
        self.assertIn("xsettingsd", self.read_log("pkill"))
        self.assertIn("HUP", self.read_log("pkill"))

    def test_xsettingsd_untouched_when_it_has_no_config(self):
        (self.home / ".config/xsettingsd/xsettingsd.conf").unlink()
        result = self.apply_dark()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / ".config/xsettingsd/xsettingsd.conf").exists())
        self.assertNotIn("xsettingsd", self.read_log("pkill"))

    def test_gsettings_copy_is_still_written(self):
        self.apply_light()
        log = self.read_log("gsettings")
        self.assertIn("color-scheme prefer-light", log)
        self.assertIn("gtk-theme adw-gtk3", log)


class StarshipPaletteTests(PlasmaApplyTestCase):
    """Starship only follows the wallpaper if the apply selects the palette."""

    def setUp(self):
        super().setUp()
        self.starship = self.home / ".config/starship.toml"
        self.starship.write_text(STARSHIP_CONF, encoding="utf-8")

    def read_starship(self):
        return self.starship.read_text(encoding="utf-8")

    def starship_config(self):
        return tomllib.loads(self.read_starship())

    def test_apply_selects_the_generated_palette(self):
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.starship_config()["palette"], "matugen")

    def test_generated_entries_replace_the_managed_block(self):
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.starship_config()["palettes"]["matugen"],
            {
                "color0": "#fdf8fb",
                "color3": "#1f1637",
                "cyan": "#ba1a1a",
                "purple": "#615c6c",
            },
        )

    def test_unrelated_keys_and_other_palettes_survive(self):
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.starship_config()
        self.assertEqual(config["azure"]["symbol"], "☁️ ")
        self.assertEqual(config["palettes"]["noctalia"], {"cyan": "#b9cbbf"})
        self.assertIn('"$schema"', self.read_starship())
        self.assertIn("# >>> NOCTALIA STARSHIP PALETTE >>>", self.read_starship())

    def test_palette_key_is_inserted_when_the_config_has_none(self):
        self.starship.write_text(
            STARSHIP_CONF_WITHOUT_PALETTE_KEY, encoding="utf-8"
        )
        result = self.apply_light()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.starship_config()["palette"], "matugen")
        text = self.read_starship()
        key_line = next(
            index
            for index, line in enumerate(text.splitlines())
            if re.match(r"^palette\s*=", line)
        )
        first_table = next(
            index
            for index, line in enumerate(text.splitlines())
            if line.startswith("[")
        )
        self.assertLess(key_line, first_table)

    def test_repeated_apply_keeps_a_single_palette_key(self):
        self.assertEqual(self.apply_light().returncode, 0)
        first = self.read_starship()
        self.assertEqual(self.apply_light().returncode, 0)
        self.assertEqual(self.read_starship(), first)
        keys = [
            line
            for line in self.read_starship().splitlines()
            if re.match(r"^palette\s*=", line)
        ]
        self.assertEqual(keys, ['palette = "matugen"'])


if __name__ == "__main__":
    unittest.main()
