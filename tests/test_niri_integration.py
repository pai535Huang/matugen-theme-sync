import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "niri_integration", ROOT / "bin/niri_integration.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BEGIN = "// BEGIN MATUGEN THEME SYNC"
END = "// END MATUGEN THEME SYNC"


class ManagedBlockTests(unittest.TestCase):
    def test_upsert_appends_exactly_one_block(self):
        result = MODULE.upsert_managed_block("layout {}\n", BEGIN, END, 'include "./colors.kdl"')
        self.assertEqual(result.count(BEGIN), 1)
        self.assertTrue(result.endswith(f'{BEGIN}\ninclude "./colors.kdl"\n{END}\n'))

    def test_upsert_replaces_existing_body(self):
        old = f"header\n{BEGIN}\nold\n{END}\nfooter\n"
        result = MODULE.upsert_managed_block(old, BEGIN, END, "new")
        self.assertEqual(result, f"header\n{BEGIN}\nnew\n{END}\nfooter\n")

    def test_remove_preserves_surrounding_edits(self):
        text = f"before\n{BEGIN}\nmanaged\n{END}\nafter\n"
        self.assertEqual(MODULE.remove_managed_block(text, BEGIN, END), "before\nafter\n")

    def test_partial_or_duplicate_markers_raise(self):
        cases = (f"{BEGIN}\nbody\n", f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}\n")
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(MODULE.ManagedBlockError):
                    MODULE.upsert_managed_block(text, BEGIN, END, "new")
