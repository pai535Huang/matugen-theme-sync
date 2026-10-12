import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
              for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@unittest.skipUnless(shutil.which("matugen"), "requires the matugen executable")
class PywalfoxTemplatesTest(unittest.TestCase):
    def test_hooks_send_rendered_mode_before_refresh(self):
        for desktop in ("gnome", "niri"):
            entry = tomllib.loads((ROOT / f"matugen/config-{desktop}.toml").read_text())["templates"]["pywalfox"]
            for mode in ("light", "dark"):
                with self.subTest(desktop=desktop, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    tmp = Path(tmp)
                    calls = tmp / "calls"
                    stub = tmp / "pywalfox"
                    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PYWALFOX_TEST_CALLS"\n')
                    stub.chmod(0o755)
                    template = tmp / "input.txt"
                    template.write_text("{{mode}}")
                    config = tmp / "config.toml"
                    config.write_text(
                        "[config]\n[templates.pywalfox]\n"
                        f"input_path = {json.dumps(str(template))}\n"
                        f"output_path = {json.dumps(str(tmp / 'output.txt'))}\n"
                        f"post_hook = {json.dumps(entry['post_hook'])}\n"
                    )
                    result = subprocess.run(
                        ["matugen", "-c", str(config), "color", "hex", "#246a9c", "--mode", mode],
                        env={**os.environ, "PATH": str(tmp) + os.pathsep + os.environ["PATH"],
                             "PYWALFOX_TEST_CALLS": str(calls)},
                        capture_output=True, text=True, timeout=20,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls.read_text().splitlines(), [mode, "update"])

    def test_real_render_keeps_pywalfox_base_and_accent_contrast(self):
        # Render the actual mode routing, with all live hooks removed and outputs
        # redirected to a temporary directory. Do not change the user's theme.
        for desktop in ("plasma", "gnome", "niri"):
            entry = tomllib.loads((ROOT / f"matugen/config-{desktop}.toml").read_text())["templates"]["pywalfox"]
            for mode in ("light", "dark"):
                for seed in ("#246a9c", "#bb7035"):
                    with self.subTest(desktop=desktop, mode=mode, seed=seed), tempfile.TemporaryDirectory() as tmp:
                        tmp = Path(tmp)
                        def local(path):
                            return str(ROOT / "matugen/templates" / Path(path).name)
                        config = "[config]\n[templates.pywalfox]\n"
                        config += f"input_path = {json.dumps(local(entry['input_path']))}\n"
                        modes = entry["input_path_modes"]
                        config += "input_path_modes = { " + ", ".join(
                            f"{key} = {json.dumps(local(value))}" for key, value in modes.items()
                        ) + " }\n"
                        output = tmp / "colors.json"
                        config += f"output_path = {json.dumps(str(output))}\n"
                        config_path = tmp / "config.toml"
                        config_path.write_text(config)
                        result = subprocess.run(
                            ["matugen", "-c", str(config_path), "color", "hex", seed,
                             "--mode", mode, "-t", "scheme-fidelity"],
                            capture_output=True, text=True, timeout=20,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        colors = json.loads(output.read_text())["colors"]
                        self.assertEqual(list(colors), [f"color{i}" for i in range(16)])
                        for value in colors.values():
                            self.assertRegex(value, r"^#[0-9a-fA-F]{6}$")
                        self.assertLess(luminance(colors["color0"]), 0.05)
                        self.assertGreater(luminance(colors["color7"]), 0.6)
                        self.assertGreater(luminance(colors["color15"]), 0.6)
                        # Pywalfox light mode selects color3; dark mode selects
                        # color10. These must remain dark/light respectively.
                        accent = luminance(colors["color3" if mode == "light" else "color10"])
                        contrast = 1.05 / (accent + 0.05) if mode == "light" else (accent + 0.05) / (luminance("#111416") + 0.05)
                        self.assertGreaterEqual(contrast, 4.5)


if __name__ == "__main__":
    unittest.main()
