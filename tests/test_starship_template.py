import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "matugen/templates/starship-colors.toml"

COLORS = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))["palettes"]["matugen"]


def role(name):
    return "{{colors.%s.default.hex}}" % name


# Starship resolves a style's colour name through the active palette, so a
# palette entry named after a built-in colour silently replaces what every
# module using that name renders. These are the names Starship 1.26's default
# styles reference; any name missing here falls back to the terminal's own
# ANSI colour and the prompt stops following the wallpaper.
DEFAULT_STYLE_NAMES = (
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "purple",
)

BRIGHT_NAMES = tuple("bright-%s" % name for name in DEFAULT_STYLE_NAMES)

# Material 3 role per Starship colour name: the accent roles are shared by the
# names that mean the same thing, and the container roles give the "bright"
# variants a distinct tint instead of a duplicate of their base colour.
EXPECTED_ROLES = {
    "cyan": "primary",
    "blue": "primary",
    "bright-cyan": "primary_container",
    "bright-blue": "primary_container",
    "purple": "secondary",
    "magenta": "secondary",
    "bright-purple": "secondary_container",
    "bright-magenta": "secondary_container",
    "green": "tertiary",
    "bright-green": "tertiary_container",
    "yellow": "tertiary_container",
    "bright-yellow": "tertiary_container",
    "red": "error",
    "bright-red": "error",
    "white": "on_surface",
    "bright-white": "on_surface",
    "black": "surface",
    "bright-black": "outline",
}

# Positional entries kept so existing configurations that reference
# fg:color0..fg:color9 (and the previously generated block) keep working.
POSITIONAL_ROLES = {
    "color0": "surface",
    "color1": "surface_container",
    "color2": "primary",
    "color3": "primary_container",
    "color4": "secondary",
    "color5": "tertiary",
    "color6": "error",
    "color7": "on_surface",
    "color8": "outline",
    "color9": "on_surface_variant",
}


class StarshipTemplateTest(unittest.TestCase):
    def test_template_declares_a_single_named_palette(self) -> None:
        document = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(list(document["palettes"]), ["matugen"])

    def test_default_style_colour_names_are_defined(self) -> None:
        for name in DEFAULT_STYLE_NAMES + BRIGHT_NAMES:
            with self.subTest(name=name):
                self.assertIn(name, COLORS)

    def test_style_colour_names_map_to_material_roles(self) -> None:
        for name, material_role in EXPECTED_ROLES.items():
            with self.subTest(name=name):
                self.assertEqual(COLORS[name], role(material_role))

    def test_positional_colours_are_kept(self) -> None:
        for name, material_role in POSITIONAL_ROLES.items():
            with self.subTest(name=name):
                self.assertEqual(COLORS[name], role(material_role))
