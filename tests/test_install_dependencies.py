import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


class InstallDependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.local_bin = self.home / ".local" / "bin"
        self.tools = self.base / "tools"
        self.answer = self.base / "answer"
        self.command_log = self.base / "commands.log"
        self.pacman_config = self.base / "pacman.conf"
        self.local_bin.mkdir(parents=True)
        self.tools.mkdir()
        self.answer.write_text("y\n", encoding="utf-8")

    def command(self, name, body="exit 0"):
        path = self.tools / name
        path.write_text(
            "#!/usr/bin/bash\n"
            f"printf '%s' '{name}' >> \"$COMMAND_LOG\"\n"
            "printf ' %s' \"$@\" >> \"$COMMAND_LOG\"\n"
            "printf '\\n' >> \"$COMMAND_LOG\"\n"
            f"{textwrap.dedent(body).strip()}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def successful_installer(self, name):
        return self.command(
            name,
            """
            printf '#!/usr/bin/bash\\nexit 0\\n' > "$HOME/.local/bin/matugen"
            /usr/bin/chmod +x "$HOME/.local/bin/matugen"
            """,
        )

    def run_bash(self, statement, *, euid="0", tty=None):
        env = os.environ.copy()
        env.update(
            {
                "PATH": str(self.tools),
                "HOME": str(self.home),
                "COMMAND_LOG": str(self.command_log),
                "MATUGEN_INSTALL_EUID": euid,
                "MATUGEN_INSTALL_TTY": str(self.answer if tty is None else tty),
                "PACMAN_CONFIG_FILE": str(self.pacman_config),
                "INSTALLER": str(INSTALLER),
            }
        )
        return subprocess.run(
            ["/usr/bin/bash", "-c", 'source "$INSTALLER"\n' + statement],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def log_lines(self):
        if not self.command_log.exists():
            return []
        return self.command_log.read_text(encoding="utf-8").splitlines()

    def test_detects_pacman_only_with_pacman_config(self):
        self.command("pacman")
        self.pacman_config.touch()
        result = self.run_bash("detect_package_manager")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "pacman")

    def test_skips_pacman_without_config_and_detects_dnf(self):
        self.command("pacman")
        self.command("dnf")
        result = self.run_bash("detect_package_manager")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "dnf")

    def test_detects_apt_get_as_debian_family(self):
        self.command("apt-get")
        result = self.run_bash("detect_package_manager")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "apt-get")

    def test_reports_no_supported_package_manager(self):
        result = self.run_bash("detect_package_manager")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_run_as_root_requires_sudo_for_non_root_user(self):
        result = self.run_bash("run_as_root true", euid="1000")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sudo", result.stderr)

    def test_existing_matugen_skips_prompt_and_install(self):
        self.command("matugen")
        self.answer.unlink()
        result = self.run_bash("ensure_matugen")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.log_lines(), [])

    def test_declined_installation_fails(self):
        self.answer.write_text("n\n", encoding="utf-8")
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation cancelled", result.stderr)

    def test_empty_answer_fails(self):
        self.answer.write_text("\n", encoding="utf-8")
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation cancelled", result.stderr)

    def test_missing_tty_fails_without_installing(self):
        missing = self.base / "missing-tty"
        result = self.run_bash("ensure_matugen", tty=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no interactive terminal", result.stderr)
        self.assertEqual(self.log_lines(), [])

    def test_pacman_install_uses_expected_arguments(self):
        self.pacman_config.touch()
        self.successful_installer("pacman")
        result = self.run_bash("ensure_matugen")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.log_lines(), ["pacman -S --needed --noconfirm matugen"]
        )

    def test_dnf_install_uses_expected_arguments(self):
        self.successful_installer("dnf")
        result = self.run_bash("ensure_matugen")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.log_lines(), ["dnf -y install matugen"])

    def test_apt_installs_cargo_then_matugen_in_local_root(self):
        self.command("apt-get")
        self.successful_installer("cargo")
        result = self.run_bash("ensure_matugen")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.log_lines(),
            [
                "apt-get update",
                "apt-get install -y cargo",
                f"cargo install --root {self.home}/.local matugen",
            ],
        )

    def test_apt_fails_when_cargo_is_unavailable(self):
        self.command("apt-get")
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cargo is unavailable", result.stderr)

    def test_ensure_reports_unsupported_package_manager(self):
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no supported package manager", result.stderr)

    def test_package_manager_failure_is_returned(self):
        self.pacman_config.touch()
        self.command("pacman", "exit 7")
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed to install matugen", result.stderr)

    def test_successful_command_without_matugen_fails_verification(self):
        self.pacman_config.touch()
        self.command("pacman")
        result = self.run_bash("ensure_matugen")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("executable was not found", result.stderr)

    def test_non_root_install_uses_sudo(self):
        self.pacman_config.touch()
        self.successful_installer("pacman")
        self.command("sudo", '"$@"')
        result = self.run_bash("ensure_matugen", euid="1000")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.log_lines(),
            [
                "sudo pacman -S --needed --noconfirm matugen",
                "pacman -S --needed --noconfirm matugen",
            ],
        )

    def test_dependency_failure_precedes_project_file_installation(self):
        self.answer.write_text("n\n", encoding="utf-8")
        result = self.run_bash("do_install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation cancelled", result.stderr)
        self.assertFalse(
            (self.home / ".local" / "share" / "matugen-theme-sync").exists()
        )

    def test_readme_documents_supported_matugen_installers(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for expected in ("pacman", "dnf", "apt-get", "Cargo", "~/.local/bin"):
            with self.subTest(expected=expected):
                self.assertIn(expected, readme)


if __name__ == "__main__":
    unittest.main()
