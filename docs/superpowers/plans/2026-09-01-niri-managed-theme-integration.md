# Niri Managed Theme Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete, reversible Niri theme integration that deploys full Waybar, Rofi, and Mako themes, connects Niri colors, and follows awww or swww wallpapers safely.

**Architecture:** A focused Python module owns marked configuration blocks, original snapshots, transaction rollback, conflict archival, and static theme deployment. The existing CLI coordinates that module around the initial Matugen generation and enables the watcher only after validation. The apply script owns wallpaper resolution; the watcher polls that single interface instead of cache internals.

**Tech Stack:** Python 3 standard library, Bash, TOML Matugen templates, KDL, GTK CSS, Rasi, Mako configuration, `unittest`, systemd user units.

**Spec:** `docs/superpowers/specs/2026-09-01-niri-managed-theme-integration-design.md`

## Global Constraints

- Preserve all existing Plasma and GNOME behavior.
- Support the locally installed baseline: Niri 26.04, awww 0.12.1, Waybar 0.15.0, Rofi 2.0.0, Mako 1.11.0, and Matugen 4.2.0.
- The first original snapshot is immutable; every apply also has a separate rollback snapshot.
- Never silently discard pre-install or post-install user edits.
- Waybar module configuration remains user-owned; Mako configuration is managed as a complete file.
- Niri and Rofi main configurations are changed only through one well-formed managed block each.
- `--no-bootstrap` must not back up, replace, activate, reload, enable, or start managed Niri application themes.
- Static themes and templates must contain no username, `/home/hjk` path, or fixed hexadecimal theme color.
- Wallpaper selection is deterministic across outputs and preserves paths containing spaces.
- Use only Python's standard library; do not add a runtime package dependency.

## File Structure

- Create `niri/waybar/style.css`: complete portable Waybar stylesheet using generated GTK named colors.
- Create `niri/rofi/matugen.rasi`: complete portable Rofi theme importing `../colors.rasi`.
- Create `niri/mako/config`: complete Mako behavior configuration with a deploy-time include placeholder.
- Create `bin/niri_integration.py`: managed-block editing, backup manifest, transactions, static deployment, validation, reload, and restoration.
- Modify `bin/matugen-theme-sync`: Niri detection, dependency reporting, transactional apply ordering, restoration, and status output.
- Modify `bin/matugen-niri-apply`: wallpaper resolution and generated-theme application.
- Modify `bin/matugen-niri-watch`: daemon-query polling through the apply script.
- Modify `matugen/config-niri.toml` and four Niri templates: dynamic colors and post-hooks.
- Modify `install.sh`: include the new `niri/` resource directory in installed copies.
- Expand `tests/test_niri_templates.py`: template and static-theme contract tests.
- Create `tests/test_niri_integration.py`: managed-block and lifecycle tests.
- Create `tests/test_theme_sync_cli.py`: desktop detection, dependency, CLI transaction, and installer resource tests.
- Create `tests/test_niri_scripts.py`: fake-daemon wallpaper resolution and watcher tests.
- Modify `README.md`: managed integration, backups, conflicts, multi-output behavior, and recovery.

---

### Task 1: Portable Full Themes and Color Templates

**Files:**
- Create: `niri/waybar/style.css`
- Create: `niri/rofi/matugen.rasi`
- Create: `niri/mako/config`
- Modify: `matugen/templates/niri-colors.kdl`
- Modify: `matugen/templates/mako-colors`
- Modify: `matugen/templates/waybar-colors.css`
- Modify: `matugen/templates/rofi-colors.rasi`
- Modify: `matugen/config-niri.toml`
- Modify: `tests/test_niri_templates.py`

**Interfaces:**
- Consumes: Matugen role syntax `{{colors.<role>.default.hex}}` and the approved local Waybar/Rofi visual baseline.
- Produces: static resource paths consumed by `NiriIntegration.deploy_static()` in Task 3; generated color paths declared by `config-niri.toml`.

- [ ] **Step 1: Replace permissive template tests with the full-theme contract**

Add these assertions to `tests/test_niri_templates.py` and change the Mako criterion expectation from `high` to `critical`:

```python
STATIC_WAYBAR = (ROOT / "niri/waybar/style.css").read_text(encoding="utf-8")
STATIC_ROFI = (ROOT / "niri/rofi/matugen.rasi").read_text(encoding="utf-8")
STATIC_MAKO = (ROOT / "niri/mako/config").read_text(encoding="utf-8")

def test_static_niri_application_themes_are_portable(self) -> None:
    for source in (STATIC_WAYBAR, STATIC_ROFI, STATIC_MAKO):
        self.assertNotIn("/home/hjk", source)
        self.assertNotRegex(source, r"#[0-9A-Fa-f]{3,8}\\b")
    self.assertIn("@MATUGEN_WAYBAR_COLORS@", STATIC_WAYBAR)
    self.assertIn('@import "../colors.rasi"', STATIC_ROFI)
    self.assertIn("@MATUGEN_MAKO_COLORS@", STATIC_MAKO)

def test_rofi_theme_defines_complete_widget_states(self) -> None:
    for widget in (
        "window", "mainbox", "inputbar", "message", "listview",
        "mode-switcher", "element", "element-text", "element-icon",
        "scrollbar", "entry", "prompt", "case-indicator",
    ):
        self.assertRegex(STATIC_ROFI, rf"(?m)^{re.escape(widget)}(?:[ .]|\\s*\\{{)")
    for state in (
        "selected.normal", "selected.active", "selected.urgent",
        "alternate.normal", "alternate.active", "alternate.urgent",
    ):
        self.assertIn(f"element {state}", STATIC_ROFI)

def test_mako_uses_supported_urgency_and_role_pairs(self) -> None:
    self.assertNotIn("[urgency=high]", MAKO)
    self.assertIn("[urgency=critical]", MAKO)
    self.assertIn("{{colors.error_container.default.hex}}", MAKO)
    self.assertIn("{{colors.on_error_container.default.hex}}", MAKO)
    self.assertIn("progress-color=", MAKO)

def test_niri_overrides_existing_focus_gradient(self) -> None:
    self.assertIn("active-gradient", NIRI_KDL)
    self.assertIn("{{colors.primary.default.hex}}", NIRI_KDL)
    self.assertIn("{{colors.tertiary.default.hex}}", NIRI_KDL)
    self.assertIn("angle=135", NIRI_KDL)
```

- [ ] **Step 2: Run the focused tests and verify the new contract fails**

Run: `python -m unittest tests.test_niri_templates -v`

Expected: FAIL because the three static resources do not exist yet and because the current Mako/Niri templates use `high` and a solid focus color.

- [ ] **Step 3: Add the static resources and refine dynamic templates**

Implement the files with these exact integration points:

```css
/* niri/waybar/style.css */
@import url("@MATUGEN_WAYBAR_COLORS@");

* {
    font-family: "JetBrains Mono Nerd Font", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
    min-height: 0;
}
```

Carry over the approved local module padding and workspace states. Add `tooltip`, `.modules-left`, `.modules-center`, `.modules-right`, disabled/muted states, and selectors for `cpu`, `memory`, `temperature`, `idle_inhibitor`, `power-profiles-daemon`, and `custom-power`. Use only names defined in `waybar-colors.css`.

```rasi
/* niri/rofi/matugen.rasi */
@import "../colors.rasi"

* {
    background: @surface-container;
    background-alt: @surface-container-high;
    foreground: @on-surface;
    foreground-muted: @on-surface-variant;
    accent: @primary;
    urgent: @error;
}

mainbox {
    children: [ inputbar, message, listview, mode-switcher ];
}
```

Define every widget and state named by the test. Pair selected surfaces with readable `on-*` roles instead of using accent text on an unrelated background.

```ini
# niri/mako/config
anchor=top-right
layer=overlay
width=360
default-timeout=5000
sort=-time
group-by=summary,app-name
max-visible=5
font=JetBrains Mono Nerd Font 10
markup=true
border-size=1
border-radius=8
margin=8
padding=10
include=@MATUGEN_MAKO_COLORS@

[urgency=critical]
default-timeout=0

[urgency=low]
default-timeout=3000

[app-name="kdeconnectd"]
default-timeout=0

[mode=do-not-disturb]
invisible=1
```

Change `mako-colors` to default surface/on-surface colors, a primary progress color, a low-urgency outline, and an error-container/on-error-container `critical` criterion. Change `niri-colors.kdl` to emit a 135-degree primary-to-tertiary active gradient plus the already approved border, shadow, tab, insertion, overview, recent-window, and background colors. Keep the four dynamic outputs and tolerant post-hooks in `config-niri.toml`.

- [ ] **Step 4: Run the focused tests and inspect portability**

Run: `python -m unittest tests.test_niri_templates -v`

Expected: PASS.

Run: `rg -n '/home/hjk|#[0-9A-Fa-f]{6}' niri matugen/templates/{niri-colors.kdl,waybar-colors.css,rofi-colors.rasi,mako-colors}`

Expected: no matches except Matugen token syntax containing no literal color.

- [ ] **Step 5: Commit the complete theme resources**

```bash
git add niri matugen/config-niri.toml matugen/templates/niri-colors.kdl matugen/templates/mako-colors matugen/templates/waybar-colors.css matugen/templates/rofi-colors.rasi tests/test_niri_templates.py
git commit -m "feat: add complete managed niri themes"
```

---

### Task 2: Managed Configuration Block Utilities

**Files:**
- Create: `bin/niri_integration.py`
- Create: `tests/test_niri_integration.py`

**Interfaces:**
- Consumes: plain UTF-8 Niri KDL and Rofi Rasi strings.
- Produces: `ManagedBlockError`, `upsert_managed_block(text: str, begin: str, end: str, body: str) -> str`, and `remove_managed_block(text: str, begin: str, end: str) -> str` for Task 3.

- [ ] **Step 1: Write failing tests for insertion, replacement, removal, and malformed markers**

Create `tests/test_niri_integration.py` with:

```python
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
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `python -m unittest tests.test_niri_integration.ManagedBlockTests -v`

Expected: ERROR because `bin/niri_integration.py` does not exist.

- [ ] **Step 3: Implement strict managed-block utilities**

Create `bin/niri_integration.py` with these public definitions:

```python
#!/usr/bin/env python3
import re

class ManagedBlockError(RuntimeError):
    """Raised when a managed configuration block cannot be edited safely."""

def _block_pattern(begin: str, end: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^{re.escape(begin)}\\n.*?^{re.escape(end)}\\n?",
        re.DOTALL,
    )

def _validate_markers(text: str, begin: str, end: str) -> int:
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != end_count or begin_count > 1:
        raise ManagedBlockError("managed theme markers are partial or duplicated")
    return begin_count

def upsert_managed_block(text: str, begin: str, end: str, body: str) -> str:
    count = _validate_markers(text, begin, end)
    block = f"{begin}\n{body.rstrip()}\n{end}\n"
    if count:
        return _block_pattern(begin, end).sub(block, text, count=1)
    prefix = text.rstrip("\n")
    return f"{prefix}\n\n{block}" if prefix else block

def remove_managed_block(text: str, begin: str, end: str) -> str:
    count = _validate_markers(text, begin, end)
    if not count:
        return text
    result = _block_pattern(begin, end).sub("", text, count=1)
    return re.sub(r"\n{3,}", "\n\n", result)
```

- [ ] **Step 4: Run the block utility tests**

Run: `python -m unittest tests.test_niri_integration.ManagedBlockTests -v`

Expected: PASS.

- [ ] **Step 5: Commit the isolated editing primitive**

```bash
git add bin/niri_integration.py tests/test_niri_integration.py
git commit -m "feat: add strict managed config blocks"
```

---

### Task 3: Backup, Transaction, Conflict, and Restore Lifecycle

**Files:**
- Modify: `bin/niri_integration.py`
- Modify: `tests/test_niri_integration.py`

**Interfaces:**
- Consumes: `upsert_managed_block()` and `remove_managed_block()` from Task 2; static resource directory `niri/` from Task 1.
- Produces: `NiriIntegration(home: Path, state_home: Path, resources: Path, timestamp: Callable[[], str] | None = None)`, with `begin()`, `deploy_static()`, `activate()`, `validate()`, `reload()`, `commit()`, `rollback()`, and `restore()` methods for Task 4.

- [ ] **Step 1: Add failing lifecycle tests using a temporary HOME**

Add a `NiriIntegrationTests` class with setup and the core first-apply/idempotency case:

```python
import json
import tempfile

class NiriIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.state = self.base / "state"
        self.resources = self.base / "resources"
        (self.resources / "waybar").mkdir(parents=True)
        (self.resources / "rofi").mkdir()
        (self.resources / "mako").mkdir()
        (self.resources / "waybar/style.css").write_text(
            '@import url("@MATUGEN_WAYBAR_COLORS@");\n', encoding="utf-8"
        )
        (self.resources / "rofi/matugen.rasi").write_text(
            '@import "../colors.rasi"\n', encoding="utf-8"
        )
        (self.resources / "mako/config").write_text(
            "include=@MATUGEN_MAKO_COLORS@\n", encoding="utf-8"
        )
        self.manager = MODULE.NiriIntegration(
            self.home, self.state, self.resources, timestamp=lambda: "20260901T120000"
        )

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_first_apply_keeps_immutable_original_and_is_idempotent(self):
        style = self.write(".config/waybar/style.css", "original-style\n")
        niri = self.write(".config/niri/config.kdl", "layout {}\n")
        rofi = self.write(".config/rofi/config.rasi", "configuration {}\n")
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.activate()
        self.manager.commit()
        manifest_path = self.state / "matugen-theme-sync/niri/manifest.json"
        first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn(str(style), [item["path"] for item in first_manifest["targets"].values()])
        self.assertIn('include "./colors.kdl"', niri.read_text(encoding="utf-8"))
        self.assertIn('@theme "matugen"', rofi.read_text(encoding="utf-8"))
        self.manager.begin()
        self.manager.deploy_static()
        self.manager.activate()
        self.manager.commit()
        second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(first_manifest["targets"], second_manifest["targets"])
```

Add these lifecycle tests:

```python
def test_failed_apply_rolls_back_to_pre_operation_state(self):
    style = self.write(".config/waybar/style.css", "before-operation\n")
    self.manager.begin()
    self.manager.deploy_static()
    self.assertNotEqual(style.read_text(encoding="utf-8"), "before-operation\n")
    self.manager.rollback()
    self.assertEqual(style.read_text(encoding="utf-8"), "before-operation\n")

def test_changed_managed_file_is_archived_before_update(self):
    style = self.write(".config/waybar/style.css", "original\n")
    self.manager.begin()
    self.manager.deploy_static()
    self.manager.activate()
    self.manager.commit()
    style.write_text("user-managed-edit\n", encoding="utf-8")
    self.manager.begin()
    self.manager.deploy_static()
    conflict = self.state / (
        "matugen-theme-sync/niri/conflicts/20260901T120000/waybar-style"
    )
    self.assertEqual(conflict.read_text(encoding="utf-8"), "user-managed-edit\n")
    self.manager.rollback()

def test_restore_restores_originals_removes_absent_paths_and_preserves_new_config(self):
    style = self.write(".config/waybar/style.css", "original-style\n")
    niri = self.write(".config/niri/config.kdl", "layout {}\n")
    rofi = self.write(".config/rofi/config.rasi", "configuration {}\n")
    self.manager.begin()
    self.manager.deploy_static()
    generated = self.write(".config/niri/colors.kdl", "generated\n")
    self.manager.activate()
    self.manager.commit()
    niri.write_text(niri.read_text(encoding="utf-8") + "// later-niri-edit\n", encoding="utf-8")
    rofi.write_text(rofi.read_text(encoding="utf-8") + "/* later-rofi-edit */\n", encoding="utf-8")
    self.manager.restore()
    self.assertEqual(style.read_text(encoding="utf-8"), "original-style\n")
    self.assertFalse(generated.exists())
    self.assertNotIn(MODULE.NIRI_BEGIN, niri.read_text(encoding="utf-8"))
    self.assertIn("later-niri-edit", niri.read_text(encoding="utf-8"))
    self.assertNotIn(MODULE.ROFI_BEGIN, rofi.read_text(encoding="utf-8"))
    self.assertIn("later-rofi-edit", rofi.read_text(encoding="utf-8"))

def test_malformed_block_is_archived_then_original_is_restored(self):
    niri = self.write(".config/niri/config.kdl", "layout {}\n")
    self.manager.begin()
    self.manager.deploy_static()
    self.manager.activate()
    self.manager.commit()
    malformed = f"layout {{}}\n{MODULE.NIRI_BEGIN}\nuser-edit-without-end\n"
    niri.write_text(malformed, encoding="utf-8")
    self.manager.restore()
    conflict = self.state / (
        "matugen-theme-sync/niri/conflicts/20260901T120000/niri-config"
    )
    self.assertEqual(conflict.read_text(encoding="utf-8"), malformed)
    self.assertEqual(niri.read_text(encoding="utf-8"), "layout {}\n")
```

- [ ] **Step 2: Run the lifecycle tests and verify the class is missing**

Run: `python -m unittest tests.test_niri_integration.NiriIntegrationTests -v`

Expected: ERROR with `AttributeError: module 'niri_integration' has no attribute 'NiriIntegration'`.

- [ ] **Step 3: Implement targets, atomic IO, immutable originals, and transactions**

Add these constants and class shape to `bin/niri_integration.py`:

```python
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

NIRI_BEGIN = "// BEGIN MATUGEN THEME SYNC"
NIRI_END = "// END MATUGEN THEME SYNC"
ROFI_BEGIN = "/* BEGIN MATUGEN THEME SYNC */"
ROFI_END = "/* END MATUGEN THEME SYNC */"

TARGETS = {
    "niri-config": (".config/niri/config.kdl", "patched"),
    "niri-colors": (".config/niri/colors.kdl", "generated"),
    "waybar-style": (".config/waybar/style.css", "static"),
    "waybar-colors": (".config/waybar/colors.css", "generated"),
    "rofi-config": (".config/rofi/config.rasi", "patched"),
    "rofi-theme": (".config/rofi/themes/matugen.rasi", "static"),
    "rofi-colors": (".config/rofi/colors.rasi", "generated"),
    "mako-config": (".config/mako/config", "static"),
    "mako-colors": (".config/mako/colors", "generated"),
}

class IntegrationError(RuntimeError):
    """Raised when managed theme deployment cannot complete safely."""

class NiriIntegration:
    def __init__(
        self,
        home: Path,
        state_home: Path,
        resources: Path,
        timestamp: Callable[[], str] | None = None,
    ):
        self.home = home
        self.root = state_home / "matugen-theme-sync/niri"
        self.resources = resources
        self.timestamp = timestamp or (
            lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        self.transaction = self.root / "transactions/current"
```

Implement `_sha256`, `_atomic_write`, `_snapshot_target`, `_restore_snapshot`, `_load_manifest`, and `_write_manifest`. Backups use stable target keys beneath `originals/` and `transactions/current/`, never an absolute path as a child name. `begin()` first restores a leftover `transactions/current` from a crashed process, creates originals only for manifest entries that do not exist, then snapshots every current target into the transaction directory.

- [ ] **Step 4: Implement static deployment, activation, conflicts, commit, rollback, and restore**

Use this exact source mapping and placeholder substitution:

```python
STATIC_SOURCES = {
    "waybar-style": "waybar/style.css",
    "rofi-theme": "rofi/matugen.rasi",
    "mako-config": "mako/config",
}

def _render_static(self, key: str, source: str) -> str:
    replacements = {
        "@MATUGEN_WAYBAR_COLORS@": str(self.home / ".config/waybar/colors.css"),
        "@MATUGEN_MAKO_COLORS@": str(self.home / ".config/mako/colors"),
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    if "@MATUGEN_" in source:
        raise IntegrationError(f"unresolved deployment marker in {key}")
    return source
```

`deploy_static()` archives a current static file only when the manifest has a last-deployed checksum and the current checksum differs. `activate()` creates missing Niri/Rofi main configs as empty files and upserts these bodies:

```python
NIRI_BODY = 'include "./colors.kdl"'
ROFI_BODY = '@theme "matugen"'
```

`commit()` records checksums for the three static targets and current patched configs, writes the manifest atomically, and removes the transaction. `rollback()` restores all transaction entries and removes only the transaction. `restore()` removes well-formed blocks from current patched configs, falls back to conflict-archive-plus-original-restore for malformed blocks, restores static/generated originals, removes originally absent paths, deletes manifest/originals/transactions, and preserves `conflicts/`.

- [ ] **Step 5: Add validation and tolerant live reload interfaces**

Implement command injection so tests do not touch the real session:

```python
def validate(self, run: Callable) -> None:
    commands = (
        ["niri", "validate", "-c", str(self.home / ".config/niri/config.kdl")],
        ["rofi", "-no-config", "-theme", str(self.home / ".config/rofi/themes/matugen.rasi"), "-dump-theme"],
        ["mako", "-c", str(self.home / ".config/mako/config"), "--help"],
    )
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        result = run(command, capture_output=True, text=True)
        if result.returncode != 0 or "Failed to parse config" in result.stderr:
            raise IntegrationError(f"configuration validation failed: {command[0]}")

def reload(self, run: Callable) -> list[str]:
    commands = (
        ["niri", "msg", "action", "load-config-file"],
        ["pkill", "-SIGUSR2", "waybar"],
        ["makoctl", "reload"],
    )
    warnings = []
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        result = run(command, capture_output=True, text=True)
        if result.returncode != 0:
            warnings.append(f"could not reload {command[0]}")
    return warnings
```

Validation failure is transactional; an optional application that is absent is skipped. Live reload failure is returned as a warning because an optional application may simply not be running.

- [ ] **Step 6: Run lifecycle tests and the complete integration test file**

Run: `python -m unittest tests.test_niri_integration -v`

Expected: PASS, including original immutability, rollback, conflicts, idempotency, and restore.

- [ ] **Step 7: Commit the managed lifecycle**

```bash
git add bin/niri_integration.py tests/test_niri_integration.py
git commit -m "feat: manage reversible niri theme deployment"
```

---

### Task 4: CLI Transaction Coordination and Installation Layout

**Files:**
- Modify: `bin/matugen-theme-sync`
- Modify: `install.sh`
- Create: `tests/test_theme_sync_cli.py`
- Modify: `tests/test_install_dependencies.py`

**Interfaces:**
- Consumes: `NiriIntegration` and `IntegrationError` from Task 3; existing `stream()`, `run()`, `install_file()`, and `bootstrap_command()`.
- Produces: transactional Niri branches in `cmd_apply()` and `cmd_uninstall()`, `dependency_report(de: str) -> tuple[list[str], list[str]]`, and reliable `detect_desktop()` behavior.

- [ ] **Step 1: Write failing tests for detection and dependency classification**

Load `bin/matugen-theme-sync` with `importlib.machinery.SourceFileLoader` and patch its environment/tool lookup:

```python
def test_niri_socket_wins_over_mixed_desktop_hints(self):
    with mock.patch.dict(
        MODULE.os.environ,
        {"NIRI_SOCKET": "/run/user/1000/niri.sock", "XDG_CURRENT_DESKTOP": "niri:GNOME"},
        clear=True,
    ):
        self.assertEqual(MODULE.detect_desktop(), MODULE.DE_NIRI)

def test_installed_executable_does_not_claim_inactive_desktop(self):
    with mock.patch.dict(MODULE.os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True), \
         mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/niri"):
        self.assertIsNone(MODULE.detect_desktop())

def test_niri_dependency_report_separates_optional_apps(self):
    available = {"matugen": "/bin/matugen", "niri": "/bin/niri", "awww": "/bin/awww"}
    with mock.patch.object(MODULE.shutil, "which", side_effect=available.get):
        required, optional = MODULE.dependency_report(MODULE.DE_NIRI)
    self.assertEqual(required, [])
    self.assertEqual(optional, ["makoctl", "waybar", "rofi"])
```

- [ ] **Step 2: Write failing tests for Niri apply order, rollback, no-bootstrap, and uninstall**

Use a fake integration object that appends method names to a shared call list. Assert these exact orders:

```python
self.assertEqual(
    calls,
    ["begin", "deploy_static", "bootstrap", "activate", "validate", "reload", "enable_service", "commit"],
)
```

On a bootstrap return code of 1, assert `rollback` follows `bootstrap` and `activate`, `enable_service`, and `commit` never occur. For `bootstrap=False`, assert none of `begin`, `deploy_static`, `activate`, `reload`, `enable_service`, or `commit` occur. For uninstall, assert service disable happens before `restore` and helper file removal happens afterward.

Add an installer test that reads `install.sh` and asserts the `cp -a` source list includes `"$src/niri"`.

- [ ] **Step 3: Run the new CLI tests and verify they fail**

Run: `python -m unittest tests.test_theme_sync_cli -v`

Expected: FAIL because `dependency_report` and transactional Niri coordination do not exist and the installer does not copy `niri/`.

- [ ] **Step 4: Implement detection and dependency reporting**

Update `detect_desktop()` in this order:

```python
if os.environ.get("NIRI_SOCKET"):
    return DE_NIRI
if "niri" in hints:
    return DE_NIRI
if "plasma" in hints or "kde" in hints:
    return DE_PLASMA
if "gnome" in hints or "ubuntu:gnome" in hints:
    return DE_GNOME
return None
```

Do not infer an active desktop from installed executables. Implement `dependency_report()` with `matugen`, desktop-specific control tools, and an awww-or-swww requirement in the required list; put `makoctl`, `waybar`, and `rofi` in the Niri optional list. Keep `check_dependencies()` as the output adapter and print separate “缺少依赖” and “未安装可选组件” messages.

- [ ] **Step 5: Integrate `NiriIntegration` into apply and uninstall**

Add `NIRI_RESOURCES_DIR = resource_root() / "niri"` and import the module from the script directory. Extract service operations into `install_service(info_de, start: bool) -> bool` and `disable_service(info_de) -> None` so tests can patch ordering without invoking systemd.

Use this Niri transaction shape in `cmd_apply()` after generic files are installed:

```python
if de == DE_NIRI and not bootstrap:
    warn("--no-bootstrap: 已安装 Niri 辅助文件，但未接管主题或启用 watcher")
    return 0

manager = None
if de == DE_NIRI:
    state_home = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state"))
    manager = NiriIntegration(HOME, state_home, NIRI_RESOURCES_DIR)
    try:
        manager.begin()
        manager.deploy_static()
        if stream(bootstrap_command(de)) != 0:
            raise IntegrationError("首次 Matugen 生成失败")
        manager.activate()
        manager.validate(subprocess.run)
        for message in manager.reload(subprocess.run):
            warn(message)
        if not install_service(info_de, start=True):
            raise IntegrationError("启用 Niri watcher 失败")
        manager.commit()
    except (OSError, IntegrationError) as exc:
        if manager is not None:
            manager.rollback()
        error(str(exc))
        return 1
```

Keep the GNOME and Plasma path semantically unchanged. In Niri uninstall, disable the service first, call `manager.restore()`, then remove the service unit and scripts. `--purge` removes Matugen configuration and the per-desktop cache, but must preserve a non-empty conflict archive and print its path.

- [ ] **Step 6: Copy Niri static resources in the top-level installer**

Change `install_files()` to:

```bash
cp -a "$src/bin" "$src/matugen" "$src/niri" "$src/systemd" "$INSTALL_DIR/"
```

Keep the existing target-name safety check and full reinstall behavior.

- [ ] **Step 7: Run focused CLI and installer tests**

Run: `python -m unittest tests.test_theme_sync_cli tests.test_install_dependencies -v`

Expected: PASS.

- [ ] **Step 8: Commit CLI coordination and install layout**

```bash
git add bin/matugen-theme-sync install.sh tests/test_theme_sync_cli.py tests/test_install_dependencies.py
git commit -m "feat: transact niri theme installation"
```

---

### Task 5: Robust Wallpaper Resolution in the Apply Script

**Files:**
- Modify: `bin/matugen-niri-apply`
- Create: `tests/test_niri_scripts.py`

**Interfaces:**
- Consumes: awww 0.12 JSON object of namespace arrays and legacy swww text output.
- Produces: `--print-wallpaper` daemon-only query interface for Task 6; normal apply accepts trigger, `--force`, and an explicit wallpaper path.

- [ ] **Step 1: Write a fake-tool shell harness and failing resolver tests**

Create `tests/test_niri_scripts.py`. In each test, create a temporary HOME, fake `awww`/`swww` executables in a temporary PATH, and real image files including `Wallpapers/a spaced name.png`. Run the script with `--print-wallpaper` and assert stdout.

Cover these exact cases:

```python
def test_awww_json_preserves_spaces_and_sorts_outputs(self):
    payload = {
        "": [
            {"name": "HDMI-A-1", "displaying": {"image": str(self.second)}},
            {"name": "eDP-1", "displaying": {"image": str(self.spaced)}},
        ]
    }
    result = self.run_query(awww_json=payload)
    self.assertEqual(result.stdout.strip(), str(self.spaced))

def test_invalid_awww_json_falls_back_to_swww_text(self):
    result = self.run_query(
        awww_stdout="not-json",
        swww_stdout=f"eDP-1: image: {self.spaced}\n",
    )
    self.assertEqual(result.stdout.strip(), str(self.spaced))

def test_print_wallpaper_has_no_directory_fallback(self):
    result = self.run_query(awww_stdout="", swww_stdout="")
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(result.stdout, "")
```

- [ ] **Step 2: Run resolver tests and verify failures**

Run: `python -m unittest tests.test_niri_scripts.NiriApplyResolverTests -v`

Expected: FAIL because `--print-wallpaper` is currently rejected and text parsing truncates paths at spaces.

- [ ] **Step 3: Implement JSON-first wallpaper resolution and print mode**

Extend argument parsing with `print_wallpaper=0` and `--print-wallpaper`. Implement `query_awww` by piping `awww query --all --json` into Python 3 code that flattens namespace arrays, retains only `displaying.image` strings, sorts `(output_name.casefold(), image_path)`, and prints the first existing file. Send multi-output choice diagnostics to stderr so stdout remains machine-readable.

Implement legacy parsing without `sed` word truncation:

```bash
query_swww() {
  local output line path
  command -v swww >/dev/null 2>&1 || return 1
  output="$(swww query 2>/dev/null || true)"
  while IFS= read -r line; do
    case "$line" in
      *"image: "*) path="${line##*image: }" ;;
      *"path: "*) path="${line##*path: }" ;;
      *) continue ;;
    esac
    if [[ -f "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done <<< "$output"
  return 1
}
```

`--print-wallpaper` tries only daemon queries and exits nonzero when neither daemon reports a valid image. Normal apply retains explicit-argument and Pictures-directory fallback behavior. Remove the `WAYLAND_DISPLAY` socket hard gate so explicit/manual generation works offline; post-hooks remain tolerant.

- [ ] **Step 4: Test normal generation with fake Matugen and required outputs**

Add a test whose fake `matugen` executable creates every path in `required_outputs`, then assert an explicit image path containing spaces reaches the fake command as one argument and that the state key is written. Add a failure test in which one generated Niri color output is missing and assert the script exits 1 without updating `last-theme.txt`.

- [ ] **Step 5: Run script tests and syntax validation**

Run: `python -m unittest tests.test_niri_scripts.NiriApplyResolverTests tests.test_niri_scripts.NiriApplyGenerationTests -v`

Expected: PASS.

Run: `bash -n bin/matugen-niri-apply`

Expected: exit 0 with no output.

- [ ] **Step 6: Commit the wallpaper resolver**

```bash
git add bin/matugen-niri-apply tests/test_niri_scripts.py
git commit -m "fix: resolve niri wallpapers from daemon output"
```

---

### Task 6: Polling Watcher Without Cache Internals

**Files:**
- Modify: `bin/matugen-niri-watch`
- Modify: `systemd/matugen-niri.service`
- Modify: `tests/test_niri_scripts.py`

**Interfaces:**
- Consumes: `matugen-niri-apply --print-wallpaper` from Task 5 and the normal `startup`/`wallpaper` triggers.
- Produces: a long-running watcher that applies only when the selected daemon wallpaper changes.

- [ ] **Step 1: Write failing watcher behavior tests with a bounded loop**

Make the watcher accept test-only environment variables without exposing new user CLI flags:

```python
env.update({
    "MATUGEN_NIRI_WATCH_INTERVAL": "0",
    "MATUGEN_NIRI_WATCH_MAX_POLLS": "3",
    "MATUGEN_NIRI_APPLY": str(fake_apply),
})
```

The fake apply script returns the sequence `one.png`, `one.png`, `two.png` for `--print-wallpaper` and logs normal invocations. Assert exactly one `wallpaper` apply occurs for `two.png`; there is no apply for the unchanged second poll. Add a no-Niri-process test by faking `pgrep` to return 1 and assert a clean exit with no apply calls.

- [ ] **Step 2: Run watcher tests and verify cache-watcher behavior fails them**

Run: `python -m unittest tests.test_niri_scripts.NiriWatcherTests -v`

Expected: FAIL because the current script ignores the test bounds and watches `~/.cache/awww` indefinitely.

- [ ] **Step 3: Replace inotify/cache logic with daemon-query polling**

Use this control flow:

```bash
APPLY="${MATUGEN_NIRI_APPLY:-$HOME/.local/bin/matugen-niri-apply}"
INTERVAL="${MATUGEN_NIRI_WATCH_INTERVAL:-3}"
MAX_POLLS="${MATUGEN_NIRI_WATCH_MAX_POLLS:-0}"

last_image=""
polls=0
while true; do
  image="$($APPLY --print-wallpaper 2>/dev/null || true)"
  if [[ -n "$image" && "$image" != "$last_image" ]]; then
    "$APPLY" wallpaper "$image" || log "Theme sync failed for wallpaper"
    last_image="$image"
  fi
  (( polls += 1 ))
  if (( MAX_POLLS > 0 && polls >= MAX_POLLS )); then
    break
  fi
  sleep "$INTERVAL"
done
```

Retain the live Niri process check and clear log messages. Remove all awww cache paths, inotify targets, Niri config watches, and polling timestamp functions. The service unit remains `Restart=on-failure`; update its description to mention the wallpaper daemon rather than a generic wallpaper file.

- [ ] **Step 4: Run watcher tests and shell syntax checks**

Run: `python -m unittest tests.test_niri_scripts.NiriWatcherTests -v`

Expected: PASS.

Run: `bash -n bin/matugen-niri-watch`

Expected: exit 0 with no output. When a user systemd instance is available, also run `systemd-analyze --user verify systemd/matugen-niri.service` and expect no unit-file errors.

- [ ] **Step 5: Commit the watcher**

```bash
git add bin/matugen-niri-watch systemd/matugen-niri.service tests/test_niri_scripts.py
git commit -m "fix: poll niri wallpaper daemon state"
```

---

### Task 7: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_niri_templates.py`
- Modify: `tests/test_theme_sync_cli.py`

**Interfaces:**
- Consumes: all user-visible behavior from Tasks 1-6.
- Produces: accurate operator documentation and final regression evidence.

- [ ] **Step 1: Add failing documentation assertions**

Add a README contract test:

```python
def test_readme_documents_managed_niri_lifecycle(self):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (
        "~/.local/state/matugen-theme-sync/niri",
        "conflicts",
        'include "./colors.kdl"',
        "Waybar",
        "Rofi",
        "Mako",
        "awww query --json",
        "uninstall",
    ):
        with self.subTest(text=text):
            self.assertIn(text, readme)
    self.assertNotIn('import "colors.kdl"', readme)
```

- [ ] **Step 2: Run the documentation test and verify it fails**

Run: `python -m unittest tests.test_niri_templates.NiriTemplateTest.test_readme_documents_managed_niri_lifecycle -v`

Expected: FAIL because README still describes manual imports and cache-based behavior.

- [ ] **Step 3: Rewrite the Niri README section**

Document:

- automatic first-apply backup and exact state path;
- managed Waybar stylesheet, Rofi theme block, complete Mako config, and Niri include block;
- immutable originals, conflict archive, rollback, and uninstall restoration;
- `awww query --json`, legacy swww fallback, paths with spaces, and deterministic first-output palette choice;
- optional Waybar/Rofi/Mako behavior;
- `--no-bootstrap` leaving application themes and watcher untouched; and
- recovery commands: inspect `manifest.json`, inspect `conflicts/`, and run `matugen-theme-sync uninstall --de niri`.

Remove the obsolete `import`, `colors.*` namespace, cache watcher, and “fixed dark colors only” wording. Keep dark-mode generation explicit.

- [ ] **Step 4: Run the complete automated suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Run syntax and repository hygiene checks**

Run: `bash -n bin/matugen-niri-apply bin/matugen-niri-watch bin/matugen-gnome-watch bin/matugen-plasma-watch install.sh`

Expected: exit 0 with no output.

Run: `python -m py_compile bin/matugen-theme-sync bin/niri_integration.py`

Expected: exit 0 with no output.

Run: `git diff --check`

Expected: exit 0 with no whitespace errors.

- [ ] **Step 6: Validate rendered configurations with installed tools**

Create an isolated temporary HOME in the test harness, render the four templates with representative `#5f6368` values, deploy the static resources through `NiriIntegration`, and run:

```bash
niri validate -c "$TEST_HOME/.config/niri/config.kdl"
rofi -no-config -theme "$TEST_HOME/.config/rofi/themes/matugen.rasi" -dump-theme
WAYLAND_DISPLAY=matugen-invalid mako -c "$TEST_HOME/.config/mako/config" --help
```

Expected: Niri reports the config valid; Rofi exits 0 after dumping the theme; Mako emits no `Failed to parse config` text. A Wayland connection error is acceptable for the isolated Mako check.

- [ ] **Step 7: Review the final diff only for intended Niri and shared detection changes**

Run: `git status --short` and `git diff --stat HEAD~7..HEAD`.

Expected: no generated caches or local `/home/hjk` configuration files are tracked; pre-existing user changes remain intact; Plasma/GNOME changes are limited to shared detection/status wording already required by Niri support.

- [ ] **Step 8: Commit documentation and final test contracts**

```bash
git add README.md tests/test_niri_templates.py tests/test_theme_sync_cli.py
git commit -m "docs: explain managed niri theme lifecycle"
```
