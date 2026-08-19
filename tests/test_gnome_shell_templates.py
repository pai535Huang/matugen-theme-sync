from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DARK = (ROOT / "matugen/templates/gnome-shell-dark.css").read_text(
    encoding="utf-8"
)
LIGHT = (ROOT / "matugen/templates/gnome-shell-light.css").read_text(
    encoding="utf-8"
)


def rule(source: str, selector_fragment: str) -> str:
    masked = re.sub(
        r"\{\{.*?\}\}",
        lambda match: match.group(0).replace("{", "‹").replace("}", "›"),
        source,
    )
    match = re.search(
        rf"(?ms){re.escape(selector_fragment)}[^{{]*\{{(.*?)\}}", masked
    )
    if match is None:
        raise AssertionError(f"missing selector: {selector_fragment}")
    return match.group(1)


class GnomeShellTemplateTest(unittest.TestCase):
    def test_light_and_dark_templates_have_matching_structure(self) -> None:
        normalized_light = LIGHT.replace(
            "{{colors.inverse_on_surface.light.hex}}",
            "{{colors.on_surface.default.hex}}",
        )
        self.assertEqual(normalized_light, DARK)

    def test_panel_buttons_have_quiet_pill_states(self) -> None:
        for source in (DARK, LIGHT):
            base = rule(source, "#panel .panel-button")
            self.assertIn("border-radius: 999px", base)
            self.assertIn("transition-duration: 150ms", base)
            hover = rule(source, "#panel .panel-button:hover")
            self.assertIn("surface_container_high", hover)
            active = rule(source, "#panel .panel-button:active")
            self.assertIn("surface_container_highest", active)

    def test_checked_toggles_use_secondary_container(self) -> None:
        for source in (DARK, LIGHT):
            checked = rule(source, ".quick-toggle:checked")
            self.assertIn("on_secondary_container", checked)
            self.assertIn("secondary_container", checked)
            self.assertNotIn("on_primary.default", checked)

    def test_floating_surfaces_have_subtle_elevation(self) -> None:
        for source in (DARK, LIGHT):
            popup = rule(source, ".popup-menu-content")
            self.assertIn("border-radius: 16px", popup)
            self.assertIn("border: 1px solid", popup)
            self.assertIn("box-shadow:", popup)
            dialog = rule(source, "#uiGroup .modal-dialog")
            self.assertIn("border-radius: 16px", dialog)

    def test_templates_have_balanced_css_and_valid_tokens(self) -> None:
        token = re.compile(r"\{\{colors\.[^}]+\}\}")
        for source in (DARK, LIGHT):
            self.assertEqual(source.count("{"), source.count("}"))
            rendered = token.sub("#5f6368", source)
            self.assertNotIn("{{colors.", rendered)


if __name__ == "__main__":
    unittest.main()
