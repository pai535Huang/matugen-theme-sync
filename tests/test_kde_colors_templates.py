from pathlib import Path
import configparser
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIGHT = (ROOT / "matugen/templates/kde-colors-light.colors").read_text(
    encoding="utf-8"
)
DARK = (ROOT / "matugen/templates/kde-colors-dark.colors").read_text(
    encoding="utf-8"
)

TOKEN = re.compile(
    r"^\{\{colors\.[a-z0-9_]+\.(light|dark|default)\.hex\}\}$"
)


def parse(source: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(source)
    return parser


def variant(source: str, section: str, key: str) -> str:
    value = parse(source)[section][key]
    match = TOKEN.match(value)
    if match is None:
        raise AssertionError(f"{section}.{key} has non-token value: {value!r}")
    return match.group(1)


def complementary_variants(source: str) -> set[str]:
    section = parse(source)["Colors:Complementary"]
    variants = set()
    for key in section:
        match = TOKEN.match(section[key])
        if match is None:
            raise AssertionError(
                f"Colors:Complementary.{key} has non-token value: "
                f"{section[key]!r}"
            )
        variants.add(match.group(1))
    return variants


class KdeColorsTemplateTest(unittest.TestCase):
    def test_complementary_group_is_entirely_dark_in_both_modes(self) -> None:
        # The lock screen, the logout/shutdown screen, and their buttons all
        # set Kirigami.Theme.colorSet to Complementary (LockScreenUi.qml,
        # Logout.qml, LogoutButton.qml) and render on hardcoded dark
        # backgrounds (Logout.qml uses an 85% black overlay).  Breeze keeps
        # this group light-on-dark in BOTH BreezeLight and BreezeDark, so the
        # group must be built from dark-mode tokens regardless of the
        # scheme's own polarity; light-mode tokens here produce dark text on
        # a dark background and are unreadable.
        for source in (LIGHT, DARK):
            self.assertEqual(
                complementary_variants(source), {"dark"},
                "Colors:Complementary must use only dark-mode tokens",
            )
            # Some dark-variant on-* tokens (e.g. on_primary_container.dark)
            # can still render near-black depending on the wallpaper palette.
            # The dark palette's canonical text color is the only token
            # guaranteed to be light, so lock/logout text must use it.
            self.assertEqual(
                parse(source)["Colors:Complementary"]["ForegroundNormal"],
                "{{colors.on_surface.dark.hex}}",
            )

    def test_view_group_follows_scheme_mode(self) -> None:
        self.assertEqual(
            variant(LIGHT, "Colors:View", "BackgroundNormal"), "light"
        )
        self.assertEqual(
            variant(LIGHT, "Colors:View", "ForegroundNormal"), "light"
        )
        self.assertEqual(
            variant(DARK, "Colors:View", "BackgroundNormal"), "dark"
        )
        self.assertEqual(
            variant(DARK, "Colors:View", "ForegroundNormal"), "dark"
        )

    def test_light_selection_is_light_surface_with_light_on_colors(self) -> None:
        # Dolphin 26.08 paints selected item text with QPalette::Text
        # (KStandardItemListWidget::textColor), which follows
        # Colors:View.ForegroundNormal, not the selection foreground. A dark
        # selection surface therefore renders dark-on-dark. In light mode the
        # selection background must be a guaranteed-light token and every
        # foreground must be a light-variant on-color.
        section = parse(LIGHT)["Colors:Selection"]
        self.assertEqual(
            section["BackgroundNormal"], "{{colors.primary_fixed.light.hex}}"
        )
        self.assertEqual(
            section["ForegroundNormal"],
            "{{colors.on_primary_fixed.light.hex}}",
        )
        for key in section:
            if key.startswith("Foreground"):
                self.assertEqual(
                    variant(LIGHT, "Colors:Selection", key), "light",
                    f"Colors:Selection.{key} must use a light-variant token",
                )

    def test_dark_selection_uses_dark_variants(self) -> None:
        # The dark selection stays dark so that both QPalette::Text (light in
        # dark mode) and HighlightedText stay readable on it.
        section = parse(DARK)["Colors:Selection"]
        self.assertEqual(
            section["BackgroundNormal"],
            "{{colors.primary_container.dark.hex}}",
        )
        self.assertEqual(
            section["ForegroundNormal"],
            "{{colors.on_primary_container.dark.hex}}",
        )
        for key in section:
            self.assertEqual(
                variant(DARK, "Colors:Selection", key), "dark",
                f"Colors:Selection.{key} must use a dark-variant token",
            )

    def test_view_focus_keeps_highlighted_text_readable(self) -> None:
        # Darkly paints focused buttons (the default dialog button) with
        # KColorScheme View FocusColor as background and HighlightedText as
        # text, and uses Highlight/HighlightedText for view focus lines.  The
        # focus decoration must therefore be a mid tone that contrasts with
        # the scheme's HighlightedText: outline in light mode (dark
        # HighlightedText) and inverse primary in dark mode (light
        # HighlightedText).  primary_container / primary are the wrong
        # polarity in each mode.
        self.assertEqual(
            parse(LIGHT)["Colors:View"]["DecorationFocus"],
            "{{colors.outline.light.hex}}",
        )
        self.assertEqual(
            parse(LIGHT)["Colors:View"]["DecorationHover"],
            "{{colors.outline.light.hex}}",
        )
        self.assertEqual(
            parse(DARK)["Colors:View"]["DecorationFocus"],
            "{{colors.inverse_primary.dark.hex}}",
        )
        self.assertEqual(
            parse(DARK)["Colors:View"]["DecorationHover"],
            "{{colors.inverse_primary.dark.hex}}",
        )


if __name__ == "__main__":
    unittest.main()
