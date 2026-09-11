import fcntl
import os
import pty
import select
import subprocess
import sys
import termios
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tests" / "kitty-live-background.py"

OSC11_REPLY = b"\x1b]11;rgb:ffff/ffff/ffff\x1b\\"
OSC11_NOT_SUPPORTED = b"\x1b]11;rgb:0000/0000/0000\x1b\\"


def _controlling_tty():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def run_helper(reply, wait=12.0):
    """Run the helper on a pty and answer its OSC 11 query like a terminal."""
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, str(HELPER)],
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=_controlling_tty,
    )
    os.close(slave)
    seen = b""
    answered = False
    deadline = os.times().elapsed + wait
    while os.times().elapsed < deadline:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(master, 256)
            except OSError:
                break
            if not chunk:
                break
            seen += chunk
            if b"\x1b]11;?" in chunk and reply is not None and not answered:
                os.write(master, reply)
                answered = True
        if process.poll() is not None:
            break
    os.close(master)
    stdout, stderr = process.communicate(timeout=5)
    return process.returncode, stdout.decode(), stderr.decode(), seen


class KittyLiveBackgroundTests(unittest.TestCase):
    def test_reports_the_background_colour_the_terminal_answers_with(self):
        code, stdout, stderr, seen = run_helper(OSC11_REPLY)
        self.assertIn(b"\x1b]11;?", seen, "helper never queried the terminal")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout.strip(), "#ffffff")

    def test_black_is_reported_rather_than_treated_as_missing(self):
        code, stdout, _, _ = run_helper(OSC11_NOT_SUPPORTED)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.strip(), "#000000")

    def test_explains_a_terminal_that_never_answers(self):
        code, stdout, stderr, _ = run_helper(None, wait=6.0)
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout.strip(), "")
        self.assertIn("no", stderr.lower())


if __name__ == "__main__":
    unittest.main()
