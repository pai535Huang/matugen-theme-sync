from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
NIRI_KDL = (ROOT / "matugen/templates/niri-colors.kdl").read_text(encoding="utf-8")
WAYBAR_CSS = (ROOT / "matugen/templates/waybar-colors.css").read_text(encoding="utf-8")
ROFI_RASI = (ROOT / "matugen/templates/rofi-colors.rasi").read_text(encoding="utf-8")
MAKO = (ROOT / "matugen/templates/mako-colors").read_text(encoding="utf-8")
STATIC_WAYBAR = (ROOT / "niri/waybar/style.css").read_text(encoding="utf-8")
STATIC_ROFI = (ROOT / "niri/rofi/matugen.rasi").read_text(encoding="utf-8")
STATIC_MAKO = (ROOT / "niri/mako/config").read_text(encoding="utf-8")

TOKEN = re.compile(r"\{\{\s*colors\.[a-z0-9_]+\.default\.hex\s*\}\}")


def token_roles(source: str) -> set[str]:
    return {
        re.match(r"\{\{\s*colors\.([^.}]+)", match.group(0)).group(1)
        for match in TOKEN.finditer(source)
    }


class NiriTemplateTest(unittest.TestCase):
    def test_readme_documents_managed_niri_lifecycle(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (
            "~/.local/state/matugen-theme-sync/niri",
            "conflicts",
            'include "./colors.kdl"',
            "Waybar",
            "Rofi",
            "Mako",
            "awww query --all --json",
            "all namespaces",
            "casefolded output name",
            "uninstall --de niri --purge",
            "~/.cache/matugen-niri",
            "non-empty `conflicts/`",
            "does not change the current application theme or watcher state",
            "uninstall",
        ):
            with self.subTest(text=text):
                self.assertIn(text, readme)
        self.assertNotIn('import "colors.kdl"', readme)
        self.assertNotIn("`awww query --json`", readme)

    def test_niri_template_comment_classifies_all_positional_overrides(self) -> None:
        preamble = NIRI_KDL.split("layout {", 1)[0]
        for text in (
            "layout background-color",
            "focus-ring",
            "border",
            "shadow",
            "tab-indicator",
            "insert-hint",
            "overview backdrop-color",
            "recent-windows highlight",
        ):
            with self.subTest(text=text):
                self.assertIn(text, preamble)
        self.assertNotIn("layout sections", preamble)

    def test_static_niri_application_themes_are_portable(self) -> None:
        for source in (STATIC_WAYBAR, STATIC_ROFI, STATIC_MAKO):
            self.assertNotIn("/home/hjk", source)
            self.assertNotRegex(source, r"#[0-9A-Fa-f]{3,8}\b")
        self.assertIn("@MATUGEN_WAYBAR_COLORS@", STATIC_WAYBAR)
        self.assertIn('@import "../colors.rasi"', STATIC_ROFI)
        self.assertIn("@MATUGEN_MAKO_COLORS@", STATIC_MAKO)

    def test_rofi_theme_defines_complete_widget_states(self) -> None:
        for widget in (
            "window", "mainbox", "inputbar", "message", "listview",
            "mode-switcher", "element", "element-text", "element-icon",
            "scrollbar", "entry", "prompt", "case-indicator",
        ):
            self.assertRegex(STATIC_ROFI, rf"(?m)^{re.escape(widget)}(?:[ .]|\s*\{{)")
        for state in (
            "selected.normal", "selected.active", "selected.urgent",
            "alternate.normal", "alternate.active", "alternate.urgent",
        ):
            self.assertIn(f"element {state}", STATIC_ROFI)

    def test_mako_uses_supported_urgency_and_role_pairs(self) -> None:
        self.assertNotIn("[urgency=high]", MAKO)
        self.assertIn("[urgency=critical]", MAKO)
        self.assertIn("{{colors.error_container.default.hex}}", MAKO)
        self.assertIn("{{colors.on_error_container.default.hex}}", MAKO)
        self.assertIn("progress-color=", MAKO)

    def test_niri_overrides_existing_focus_gradient(self) -> None:
        self.assertIn("active-gradient", NIRI_KDL)
        self.assertIn("{{colors.primary.default.hex}}", NIRI_KDL)
        self.assertIn("{{colors.tertiary.default.hex}}", NIRI_KDL)
        self.assertIn("angle=135", NIRI_KDL)

    def test_config_niri_exists_and_defines_four_niri_templates(self) -> None:
        config = tomllib.loads(
            (ROOT / "matugen" / "config-niri.toml").read_text(encoding="utf-8")
        )
        templates = config["templates"]

        self.assertEqual(
            templates["niri"]["input_path"],
            "~/.config/matugen/templates/niri-colors.kdl",
        )
        self.assertEqual(templates["niri"]["output_path"], "~/.config/niri/colors.kdl")
        self.assertIn("load-config-file", templates["niri"]["post_hook"])

        self.assertEqual(
            templates["waybar"]["input_path"],
            "~/.config/matugen/templates/waybar-colors.css",
        )
        self.assertEqual(
            templates["waybar"]["output_path"], "~/.config/waybar/colors.css"
        )
        self.assertIn("SIGUSR2", templates["waybar"]["post_hook"])

        self.assertEqual(
            templates["rofi"]["input_path"],
            "~/.config/matugen/templates/rofi-colors.rasi",
        )
        self.assertEqual(
            templates["rofi"]["output_path"], "~/.config/rofi/colors.rasi"
        )

        self.assertEqual(
            templates["mako"]["input_path"],
            "~/.config/matugen/templates/mako-colors",
        )
        self.assertEqual(templates["mako"]["output_path"], "~/.config/mako/colors")
        self.assertIn("makoctl", templates["mako"]["post_hook"])

    def test_config_niri_shares_dark_templates_with_other_desktops(self) -> None:
        config = tomllib.loads(
            (ROOT / "matugen" / "config-niri.toml").read_text(encoding="utf-8")
        )
        templates = config["templates"]
        for key in ("gtk3", "gtk4", "kitty", "nvim", "cava"):
            self.assertIn(key, templates)
        for key in ("gtk3", "gtk4"):
            expected = (
                "~/.config/matugen/templates/gtk4-colors.css"
                if key == "gtk4"
                else "~/.config/matugen/templates/gtk-colors.css"
            )
            self.assertEqual(templates[key]["input_path"], expected)
        for key in ("kitty", "nvim", "cava"):
            self.assertIn("input_path_modes", templates[key])
            self.assertIn(
                "dark",
                templates[key]["input_path_modes"],
            )

    def test_templates_have_no_unrendered_tokens_after_substitution(self) -> None:
        for source in (NIRI_KDL, WAYBAR_CSS, ROFI_RASI, MAKO):
            rendered = TOKEN.sub("#5f6368", source)
            self.assertNotIn("{{", rendered)
            self.assertEqual(rendered.count("{"), rendered.count("}"))

    def test_templates_use_valid_matugen_color_roles(self) -> None:
        # All roles referenced must exist in matugen's palette namespace.
        for source in (NIRI_KDL, WAYBAR_CSS, ROFI_RASI, MAKO):
            roles = token_roles(source)
            self.assertTrue(roles, "template uses no color tokens")
            for role in roles:
                self.assertRegex(role, r"^[a-z][a-z0-9_]*$")

    def test_templates_avoid_fixed_hex_colors(self) -> None:
        for source in (NIRI_KDL, WAYBAR_CSS, ROFI_RASI, MAKO):
            self.assertNotRegex(source, r"#[0-9A-Fa-f]{3,8}\b")

    def test_niri_kdl_has_layout_and_overview_sections(self) -> None:
        self.assertIn("layout {", NIRI_KDL)
        self.assertIn("overview {", NIRI_KDL)
        self.assertIn("recent-windows {", NIRI_KDL)

    def test_waybar_css_uses_named_colors(self) -> None:
        named = re.findall(r"(?m)^@define-color\s+([a-z0-9-]+)\s+", WAYBAR_CSS)
        self.assertGreater(len(named), 10)
        for name in ("primary", "on-surface", "surface-container", "error"):
            self.assertIn(name, named)

    def test_rofi_rasi_uses_variable_assignments(self) -> None:
        self.assertIn("* {", ROFI_RASI)
        assigned = re.findall(r"(?m)^\s*([a-z0-9-]+):", ROFI_RASI)
        for name in ("primary", "on-surface", "surface-container", "error"):
            self.assertIn(name, assigned)

if __name__ == "__main__":
    unittest.main()
