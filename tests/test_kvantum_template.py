from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SVG_PATH = ROOT / "matugen/templates/kvantum-colors.svg"
CONFIG_PATH = ROOT / "matugen/templates/kvantum-colors.kvconfig"
SVG = SVG_PATH.read_text(encoding="utf-8")
CONFIG = CONFIG_PATH.read_text(encoding="utf-8")
TOKEN = re.compile(r"\{\{colors\.[^.}]+\.default\.hex\}\}")


def element(element_id: str) -> ET.Element:
    root = ET.fromstring(SVG)
    found = root.find(f".//*[@id='{element_id}']")
    if found is None:
        raise AssertionError(f"missing SVG element: {element_id}")
    return found


def source_for(element_id: str) -> str:
    return ET.tostring(element(element_id), encoding="unicode")


def section(name: str) -> str:
    match = re.search(
        rf"(?ms)^\[{re.escape(name)}\]\n(.*?)(?=^\[|\Z)", CONFIG
    )
    if match is None:
        raise AssertionError(f"missing config section: {name}")
    return match.group(1)


class KvantumTemplateTest(unittest.TestCase):
    def test_rendered_svg_is_well_formed_and_has_valid_hex_lengths(self) -> None:
        self.assertNotRegex(SVG, r"\}\}[0-9A-Fa-f]+")
        rendered = TOKEN.sub("#5f6368", SVG)
        self.assertNotIn("{{colors.", rendered)
        ET.fromstring(rendered)
        for value in re.findall(
            r"(?<![A-Za-z0-9_-])#[0-9A-Fa-f]+(?![A-Za-z0-9_-])", rendered
        ):
            self.assertIn(len(value), (4, 5, 7, 9), value)

    def test_tooltip_is_a_neutral_floating_surface(self) -> None:
        role = "{{colors.surface_container_high.default.hex}}"
        for element_id in (
            "tooltip-normal",
            "tooltip-normal-left",
            "tooltip-normal-top",
            "tooltip-normal-right",
            "tooltip-normal-bottom",
            "tooltip-shadow-top",
            "tooltip-shadow-right",
            "tooltip-shadow-left",
            "tooltip-shadow-bottom",
        ):
            self.assertIn(role, source_for(element_id), element_id)
        for side in ("top", "right", "bottom", "left"):
            hint = element(f"tooltip-shadow-hint-{side}")
            self.assertEqual(hint.attrib.get("opacity"), "0")
        self.assertIn("tooltip_delay=350", CONFIG)
        self.assertIn(
            "tooltip.text.color={{colors.on_surface.default.hex}}", CONFIG
        )

    def test_button_states_use_progressive_neutral_overlays(self) -> None:
        expected = {
            "button-normal": ("{{colors.on_surface.default.hex}}", ".08"),
            "button-focused": ("{{colors.on_surface.default.hex}}", ".12"),
            "button-pressed": ("{{colors.on_surface.default.hex}}", ".16"),
            "button-toggled": (
                "{{colors.secondary_container.default.hex}}",
                None,
            ),
            "tbutton-normal": ("{{colors.on_surface.default.hex}}", ".08"),
            "tbutton-pressed": ("{{colors.on_surface.default.hex}}", ".16"),
            "tbutton-toggled": (
                "{{colors.secondary_container.default.hex}}",
                None,
            ),
        }
        for element_id, (role, opacity) in expected.items():
            source = source_for(element_id)
            self.assertIn(role, source, element_id)
            if opacity is not None:
                self.assertIn(f'opacity="{opacity}"', source, element_id)
        self.assertIn(
            "text.toggle.color={{colors.on_secondary_container.default.hex}}",
            section("PanelButtonCommand"),
        )

    def test_popup_input_and_tab_roles_are_coherent(self) -> None:
        self.assertIn(
            "{{colors.surface_container.default.hex}}", source_for("menu-normal")
        )
        self.assertIn(
            "{{colors.secondary_container.default.hex}}",
            source_for("menuitem-normal"),
        )
        self.assertIn(
            "text.focus.color={{colors.on_secondary_container.default.hex}}",
            section("MenuItem"),
        )
        self.assertIn(
            "{{colors.surface_container_high.default.hex}}",
            source_for("tab-toggled"),
        )
        self.assertIn(
            "{{colors.primary.default.hex}}", source_for("lineedit-focused")
        )
        self.assertIn(
            "{{colors.outline_variant.default.hex}}", source_for("lineedit-normal")
        )


if __name__ == "__main__":
    unittest.main()
