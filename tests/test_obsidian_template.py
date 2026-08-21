from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "matugen/templates/obsidian.css").read_text(encoding="utf-8")


class ObsidianTemplateTest(unittest.TestCase):
    def test_uses_documented_component_variables(self) -> None:
        for variable in (
            "--interactive-normal",
            "--interactive-hover",
            "--tab-background-active",
            "--tab-container-background",
            "--tab-radius-active",
            "--modal-background",
            "--modal-border-color",
            "--modal-radius",
        ):
            self.assertIn(variable, SOURCE)

    def test_native_components_share_modern_geometry(self) -> None:
        for selector in (
            ".workspace-tab-header",
            ".nav-file-title",
            ".suggestion-item",
            ".modal",
            ".callout",
        ):
            self.assertIn(selector, SOURCE)
        self.assertIn("border-radius: 8px", SOURCE)
        self.assertIn("border-radius: 12px", SOURCE)
        self.assertIn("transition: background-color 150ms ease", SOURCE)

    def test_translucent_states_use_modern_color_mixing(self) -> None:
        self.assertIn("color-mix(in oklch", SOURCE)
        self.assertNotIn("rgba(var(--mat-", SOURCE)

    def test_snippet_does_not_override_layout_or_typography(self) -> None:
        self.assertNotRegex(
            SOURCE, r"(?m)^\s*(font-family|--font-|--file-line-width):"
        )
        self.assertNotRegex(
            SOURCE, r"(?m)^\s*(--modal-width|--tab-width|width):"
        )
        self.assertNotIn("!important", SOURCE)

    def test_transitions_respect_reduced_motion(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", SOURCE)
        self.assertIn("transition-duration: 0.01ms", SOURCE)

    def test_tooltip_message_surface_uses_inverse_surface(self) -> None:
        # Obsidian hardcodes color: #FAFAFA on .tooltip/.notice over
        # --background-modifier-message. A light surface-container-high
        # would be unreadable, so pair it with the inverse surface.
        self.assertRegex(
            SOURCE,
            r"--background-modifier-message:\s*\{\{colors\.inverse_surface\.default\.hex\}\}",
        )

    def test_tooltip_and_notice_pair_inverse_on_surface_text(self) -> None:
        self.assertRegex(
            SOURCE,
            r"\.tooltip,\s*\.notice\s*\{[^}]*color:\s*\{\{colors\.inverse_on_surface\.default\.hex\}\}[^}]*\}",
        )

    def test_error_surfaces_pair_on_error_container_text(self) -> None:
        # Obsidian hardcodes color: var(--text-on-accent) (near-white) on
        # .tooltip.mod-error / .message.mod-error over the light
        # error_container surface.
        self.assertRegex(
            SOURCE,
            r"\.tooltip\.mod-error,\s*\.message\.mod-error\s*\{[^}]*color:\s*\{\{colors\.on_error_container\.default\.hex\}\}[^}]*\}",
        )

    def test_success_surface_pairs_on_tertiary_container_text(self) -> None:
        # Same hardcoded near-white text issue on .message.mod-success over
        # the light tertiary_container surface.
        self.assertRegex(
            SOURCE,
            r"\.message\.mod-success\s*\{[^}]*color:\s*\{\{colors\.on_tertiary_container\.default\.hex\}\}[^}]*\}",
        )

    def test_tooltip_message_surface_is_not_light_container(self) -> None:
        self.assertNotRegex(
            SOURCE,
            r"--background-modifier-message:\s*var\(--mat-surface-container-high\)",
        )

    def test_template_renders_without_unresolved_tokens(self) -> None:
        token = re.compile(r"\{\{colors\.[^}]+\}\}")
        rendered = token.sub("#5f6368", SOURCE)
        self.assertNotIn("{{colors.", rendered)
        self.assertEqual(rendered.count("{"), rendered.count("}"))


if __name__ == "__main__":
    unittest.main()
