from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
GTK3_PATH = ROOT / "matugen/templates/gtk-colors.css"
GTK4_PATH = ROOT / "matugen/templates/gtk4-colors.css"
GTK3 = GTK3_PATH.read_text(encoding="utf-8")
GTK4 = GTK4_PATH.read_text(encoding="utf-8") if GTK4_PATH.exists() else ""
TOKEN = re.compile(r"\{\{colors\.[^}]+\}\}")


def named_color(source: str, name: str) -> str:
    match = re.search(
        rf"(?m)^@define-color\s+{re.escape(name)}\s+([^;]+);$", source
    )
    if match is None:
        raise AssertionError(f"missing named color: {name}")
    return match.group(1).strip()


def css_variable(source: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*--{re.escape(name)}:\s*([^;]+);$", source)
    if match is None:
        raise AssertionError(f"missing CSS variable: --{name}")
    return match.group(1).strip()


class GtkTemplateTest(unittest.TestCase):
    def test_desktop_configs_route_gtk4_to_its_own_template(self) -> None:
        for config_name in ("config-gnome.toml", "config-plasma.toml"):
            config = tomllib.loads(
                (ROOT / "matugen" / config_name).read_text(encoding="utf-8")
            )
            templates = config["templates"]
            self.assertEqual(
                templates["gtk3"]["input_path"],
                "~/.config/matugen/templates/gtk-colors.css",
            )
            self.assertEqual(
                templates["gtk4"]["input_path"],
                "~/.config/matugen/templates/gtk4-colors.css",
            )
            self.assertEqual(
                templates.get("gtk3_import"),
                {
                    "input_path": "~/.config/matugen/templates/gtk-import.css",
                    "output_path": "~/.config/gtk-3.0/gtk.css",
                },
            )
            self.assertEqual(
                templates.get("gtk4_import"),
                {
                    "input_path": "~/.config/matugen/templates/gtk-import.css",
                    "output_path": "~/.config/gtk-4.0/gtk.css",
                },
            )

    def test_gtk3_uses_adw_named_colors_with_balanced_roles(self) -> None:
        expected = {
            "accent_color": "{{colors.primary.default.hex}}",
            "accent_bg_color": "{{colors.primary.default.hex}}",
            "accent_fg_color": "{{colors.on_primary.default.hex}}",
            "window_bg_color": "{{colors.surface_container_low.default.hex}}",
            "window_fg_color": "{{colors.on_surface.default.hex}}",
            "view_bg_color": "{{colors.surface.default.hex}}",
            "view_fg_color": "{{colors.on_surface.default.hex}}",
            "headerbar_bg_color": "{{colors.surface_container.default.hex}}",
            "sidebar_bg_color": "{{colors.surface_container.default.hex}}",
            "card_bg_color": "{{colors.surface.default.hex}}",
            "dialog_bg_color": "{{colors.surface_container_low.default.hex}}",
            "popover_bg_color": "{{colors.surface_container_high.default.hex}}",
        }
        for name, value in expected.items():
            self.assertEqual(named_color(GTK3, name), value)

        self.assertNotIn(":root", GTK3)
        self.assertNotRegex(GTK3, r"(?m)^\s*--[a-z-]+:")

    def test_gtk4_covers_current_libadwaita_surface_and_state_variables(self) -> None:
        self.assertTrue(GTK4_PATH.exists(), GTK4_PATH)
        for name in (
            "accent-color",
            "accent-bg-color",
            "accent-fg-color",
            "destructive-color",
            "destructive-bg-color",
            "destructive-fg-color",
            "error-color",
            "error-bg-color",
            "error-fg-color",
            "window-bg-color",
            "window-fg-color",
            "view-bg-color",
            "view-fg-color",
            "headerbar-bg-color",
            "headerbar-fg-color",
            "headerbar-border-color",
            "headerbar-backdrop-color",
            "headerbar-shade-color",
            "headerbar-darker-shade-color",
            "sidebar-bg-color",
            "sidebar-fg-color",
            "sidebar-backdrop-color",
            "sidebar-border-color",
            "sidebar-shade-color",
            "secondary-sidebar-bg-color",
            "secondary-sidebar-fg-color",
            "secondary-sidebar-backdrop-color",
            "secondary-sidebar-border-color",
            "secondary-sidebar-shade-color",
            "card-bg-color",
            "card-fg-color",
            "card-shade-color",
            "dialog-bg-color",
            "dialog-fg-color",
            "popover-bg-color",
            "popover-fg-color",
            "popover-shade-color",
            "overview-bg-color",
            "overview-fg-color",
            "thumbnail-bg-color",
            "thumbnail-fg-color",
            "active-toggle-bg-color",
            "active-toggle-fg-color",
            "shade-color",
        ):
            self.assertEqual(css_variable(GTK4, name), f"@{name.replace('-', '_')}")

    def test_gtk4_uses_one_source_for_named_and_variable_states(self) -> None:
        expected = {
            "accent_bg_color": "{{colors.primary.default.hex}}",
            "accent_fg_color": "{{colors.on_primary.default.hex}}",
            "overview_bg_color": "{{colors.surface_container_low.default.hex}}",
            "overview_fg_color": "{{colors.on_surface.default.hex}}",
            "active_toggle_bg_color": "{{colors.secondary_container.default.hex}}",
            "active_toggle_fg_color": "{{colors.on_secondary_container.default.hex}}",
        }
        for name, value in expected.items():
            self.assertEqual(named_color(GTK4, name), value)
            self.assertEqual(css_variable(GTK4, name.replace("_", "-")), f"@{name}")

    def test_templates_avoid_fixed_brightness_and_extreme_surface_roles(self) -> None:
        for source in (GTK3, GTK4):
            self.assertNotIn("primary_fixed", source)
            self.assertNotIn("surface_dim", source)
            self.assertNotRegex(source, r"#[0-9A-Fa-f]{3,8}\b")

    def test_templates_do_not_override_widget_geometry_or_transitions(self) -> None:
        comment = re.compile(r"/\*.*?\*/", re.DOTALL)
        gtk3_body = comment.sub("", GTK3).strip()
        for line in gtk3_body.splitlines():
            if line.strip():
                self.assertRegex(line, r"^@define-color\s+[a-z_]+\s+.+;$")

        gtk4_body = comment.sub("", GTK4).strip()
        named_block, separator, variable_block = gtk4_body.partition(":root {")
        self.assertEqual(separator, ":root {")
        for line in named_block.splitlines():
            if line.strip():
                self.assertRegex(line, r"^@define-color\s+[a-z_]+\s+.+;$")
        self.assertTrue(variable_block.rstrip().endswith("}"))
        variable_lines = variable_block.rstrip()[:-1].strip().splitlines()
        for line in variable_lines:
            if line.strip():
                self.assertRegex(line.strip(), r"^--[a-z-]+:\s+@[a-z_]+;$")

        allowed_roles = {
            "primary",
            "on_primary",
            "error",
            "on_error",
            "surface_container_low",
            "on_surface",
            "surface",
            "surface_container",
            "shadow",
            "surface_container_high",
            "secondary_container",
            "on_secondary_container",
        }
        for source in (GTK3, GTK4):
            roles = set(re.findall(r"\{\{colors\.([^.}]+)\.default\.hex\}\}", source))
            self.assertLessEqual(roles, allowed_roles)
            rendered = TOKEN.sub("#5f6368", source)
            self.assertNotIn("{{colors.", rendered)
            self.assertEqual(rendered.count("{"), rendered.count("}"))


if __name__ == "__main__":
    unittest.main()
