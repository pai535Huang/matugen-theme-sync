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


if __name__ == "__main__":
    unittest.main()
