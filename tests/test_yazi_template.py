from pathlib import Path
import hashlib
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "matugen/templates/yazi-theme.toml").read_text(encoding="utf-8")
TOKEN = re.compile(r"\{\{.*?\}\}")


def rendered_theme() -> dict:
    rendered = TOKEN.sub("#5f6368", SOURCE)
    if "{{colors." in rendered:
        raise AssertionError("unresolved template expression")
    return tomllib.loads(rendered)


class YaziTemplateTest(unittest.TestCase):
    def test_rendered_theme_is_valid_toml(self) -> None:
        theme = rendered_theme()
        for section in (
            "mgr",
            "indicator",
            "tabs",
            "mode",
            "status",
            "which",
            "confirm",
            "spot",
            "notify",
            "pick",
            "input",
            "cmp",
            "tasks",
            "help",
            "filetype",
            "icon",
        ):
            self.assertIn(section, theme)

    def test_file_rules_and_icon_tables_are_byte_for_byte_unchanged(self) -> None:
        protected_tail = SOURCE[SOURCE.index("# : File-specific styles") :]
        self.assertEqual(
            hashlib.sha256(protected_tail.encode()).hexdigest(),
            "2691ea379d61d6543779f0bdd4bb17ab27d45bc4fb8170e5018a87f9d096dc8a",
        )
        self.assertEqual(len(protected_tail.splitlines()), 766)

    def test_navigation_uses_container_hierarchy(self) -> None:
        self.assertIn(
            'active    = { fg = "{{colors.on_secondary_container.default.hex}}", bg = "{{colors.secondary_container.default.hex}}", bold = true }',
            SOURCE,
        )
        self.assertIn(
            'normal_main = { bg = "{{colors.primary_container.default.hex}}", fg = "{{colors.on_primary_container.default.hex}}", bold = true }',
            SOURCE,
        )
        self.assertIn(
            'border_style  = { fg = "{{colors.outline_variant.default.hex}}" }',
            SOURCE,
        )

    def test_separators_are_single_cell_glyph_candidates(self) -> None:
        theme = rendered_theme()
        glyphs = (
            theme["mgr"]["border_symbol"],
            theme["indicator"]["padding"]["open"],
            theme["indicator"]["padding"]["close"],
            theme["tabs"]["sep_inner"]["open"],
            theme["tabs"]["sep_inner"]["close"],
            theme["status"]["sep_left"]["open"],
            theme["status"]["sep_left"]["close"],
            theme["status"]["sep_right"]["open"],
            theme["status"]["sep_right"]["close"],
        )
        for glyph in glyphs:
            self.assertEqual(len(glyph), 1, glyph)

    def test_global_ui_has_no_hard_coded_colors(self) -> None:
        global_ui = SOURCE[: SOURCE.index("# : File-specific styles")]
        self.assertNotRegex(global_ui, r"#[0-9A-Fa-f]{6}")

    def test_overlays_use_quiet_borders_and_clear_selected_states(self) -> None:
        theme = rendered_theme()
        for section in (
            "which",
            "confirm",
            "spot",
            "pick",
            "input",
            "cmp",
            "tasks",
            "help",
        ):
            self.assertIn(section, theme)
            self.assertIn("border", theme[section], section)
            self.assertEqual(theme[section]["border"]["fg"], "#5f6368")
        self.assertIn("secondary_container.default.hex", SOURCE)
        self.assertIn('separator = "  ›  "', SOURCE)

    def test_help_uses_current_yazi_keys(self) -> None:
        help_theme = rendered_theme()["help"]
        self.assertEqual(set(help_theme), {"border", "chord", "action", "hovered"})


if __name__ == "__main__":
    unittest.main()
