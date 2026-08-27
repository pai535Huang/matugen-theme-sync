from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIGHT = (ROOT / "matugen/templates/nvim-colors-light.vim").read_text(
    encoding="utf-8"
)
DARK = (ROOT / "matugen/templates/nvim-colors-dark.vim").read_text(
    encoding="utf-8"
)
TOKEN = re.compile(
    r"^\{\{\s*(?:colors|base16)\.[a-z0-9_]+\.(?:light|dark|default)\.hex\s*\}\}$"
)


def groups(source: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in source.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^hi\s+(\w+)\s+(.+)$", line)
        if match is None:
            raise AssertionError(f"unexpected hi line: {line!r}")
        name, rest = match.groups()
        guibg = guifg = None
        for part in re.split(r"\s+(?=guibg=|guifg=)", rest):
            if part.startswith("guibg="):
                guibg = part[len("guibg="):].strip()
            elif part.startswith("guifg="):
                guifg = part[len("guifg="):].strip()
        if guibg is None or guifg is None:
            raise AssertionError(f"missing guibg/guifg in line: {line!r}")
        if guibg != "None" and TOKEN.match(guibg) is None:
            raise AssertionError(f"{name} guibg is not a token: {guibg!r}")
        if TOKEN.match(guifg) is None:
            raise AssertionError(f"{name} guifg is not a token: {guifg!r}")
        result[name] = f"guibg={guibg} guifg={guifg}"
    return result


def token_name(token: str) -> str:
    name = token.strip()[len("{{"):-len("}}")].strip()
    return re.sub(r"\.(light|dark|default)\.hex$", "", name)


class NvimTemplateTest(unittest.TestCase):
    def test_configs_route_nvim_to_mode_templates(self) -> None:
        for config_name in ("config-gnome.toml", "config-plasma.toml"):
            config = tomllib.loads(
                (ROOT / "matugen" / config_name).read_text(encoding="utf-8")
            )
            templates = config["templates"]["nvim"]
            self.assertEqual(
                templates["input_path"],
                "~/.config/matugen/templates/nvim-colors-dark.vim",
            )
            self.assertEqual(
                templates["input_path_modes"],
                {
                    "light": "~/.config/matugen/templates/nvim-colors-light.vim",
                    "dark": "~/.config/matugen/templates/nvim-colors-dark.vim",
                },
            )
            self.assertEqual(
                templates["output_path"], "~/.config/nvim/colors/matugen.vim"
            )

    def test_light_uses_dark_foregrounds_on_transparent_light_background(
        self,
    ) -> None:
        # In light mode the buffer background is transparent, so kitty's
        # near-white surface shows through and code colors must be dark.
        # Using base16 tokens here was the original bug: base16 follows the
        # generation mode, so light mode produced light-on-light text.
        self.assertNotIn(
            "base16", LIGHT,
            "light template must not use mode-following base16 tokens",
        )
        light = groups(LIGHT)
        # Comments and body text are mid-to-dark neutrals.
        self.assertEqual(
            light["Comment"],
            "guibg=None guifg={{ colors.on_surface_variant.default.hex }}",
        )
        self.assertEqual(
            light["Identifier"],
            "guibg=None guifg={{ colors.on_surface.default.hex }}",
        )
        # Every foreground is a dark-on-light token (contrast >= 4.4:1 on
        # the light surface, verified against the wallpaper palette).
        dark_tokens = {
            "colors.on_surface_variant", "colors.on_surface", "colors.primary",
            "colors.secondary", "colors.tertiary", "colors.tertiary_container",
            "colors.on_primary_fixed_variant", "colors.on_tertiary_fixed_variant",
            "colors.on_secondary_container", "colors.on_error_container",
            "colors.on_primary", "colors.on_primary_container",
        }
        for name, line in light.items():
            guifg = line.split("guifg=", 1)[1]
            self.assertIn(
                token_name(guifg), dark_tokens,
                f"{name} uses {token_name(guifg)} which is not dark-on-light",
            )

    def test_dark_uses_light_foregrounds_on_transparent_dark_background(
        self,
    ) -> None:
        dark = groups(DARK)
        self.assertEqual(
            dark["Comment"], "guibg=None guifg={{ base16.base03.default.hex }}"
        )
        light_tokens = {
            "base16.base03", "base16.base05", "base16.base06", "base16.base08",
            "base16.base09", "base16.base0a", "base16.base0b", "base16.base0c",
            "base16.base0d", "base16.base0e", "base16.base0f",
            "colors.on_surface_variant", "colors.on_surface", "colors.primary",
            "colors.on_primary", "colors.primary_container",
            "colors.on_primary_container", "colors.error_container",
            "colors.on_error_container", "colors.secondary_container",
            "colors.on_secondary_container",
        }
        for name, line in dark.items():
            guifg = line.split("guifg=", 1)[1]
            self.assertIn(
                token_name(guifg), light_tokens,
                f"{name} uses {token_name(guifg)} which is not light-on-dark",
            )

    def test_light_selection_uses_light_surface_with_dark_text(self) -> None:
        parsed = groups(LIGHT)
        self.assertEqual(
            parsed["Selection"],
            "guibg={{ colors.secondary_container.default.hex }} "
            "guifg={{ colors.on_secondary_container.default.hex }}",
        )

    def test_dark_selection_uses_dark_surface_with_light_text(self) -> None:
        parsed = groups(DARK)
        self.assertEqual(
            parsed["Selection"],
            "guibg={{ colors.secondary_container.default.hex }} "
            "guifg={{ colors.on_secondary_container.default.hex }}",
        )


if __name__ == "__main__":
    unittest.main()
