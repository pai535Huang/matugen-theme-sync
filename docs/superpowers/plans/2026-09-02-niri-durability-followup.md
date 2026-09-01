# Niri Durability Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three load-bearing residuals from the managed Niri integration final review: canonical shared state paths, durable publication of Matugen-generated colors, and safe uninstall recovery of an interrupted apply.

**Architecture:** Keep the existing transaction and lock design. Normalize the XDG state root at both Python and shell entry points, add an explicit durability barrier for externally generated targets immediately before the commit journal, and make restore recover any pending transaction before reading the uninstall manifest.

**Tech Stack:** Python 3 standard library (`pathlib`, `os`, `fcntl`, `unittest`), Bash, Git.

**Spec:** `docs/superpowers/specs/2026-09-01-niri-managed-theme-integration-design.md`

## Global Constraints

- Work in the existing checkout because the original Niri baseline and user-owned watcher edits are already present there.
- Never reset, stash, clean, or modify the unstaged user-owned `bin/matugen-gnome-watch` and `bin/matugen-plasma-watch` changes.
- Preserve the stable lifecycle lock outside the purgeable `.../matugen-theme-sync/niri` root.
- Preserve immutable originals, conflict archives, journal-last commit cleanup, and existing GNOME/Plasma behavior.
- Treat an empty or relative `XDG_STATE_HOME` as invalid and fall back to `$HOME/.local/state` in both Python and Bash.
- Every behavioral change starts with a failing regression test and ends with focused plus full-suite verification.

---

### Task 1: Canonicalize the Shared Niri State Root

**Files:**
- Modify: `bin/matugen-theme-sync`
- Modify: `bin/matugen-niri-apply`
- Modify: `tests/test_theme_sync_cli.py`
- Modify: `tests/test_niri_scripts.py`

**Interfaces:**
- Produces: `resolve_state_home() -> Path` in `bin/matugen-theme-sync`.
- Preserves: the lock path `<state-home>/matugen-theme-sync/niri.lock` used by Python lifecycle operations and Bash generation.

- [ ] **Step 1: Add failing Python state-root tests**

Add tests that patch `HOME`, `XDG_STATE_HOME`, and the current directory, then assert:

```python
self.assertEqual(MODULE.resolve_state_home(), home / ".local/state")
```

for an unset value, an empty value, and a relative value such as `relative-state`. Add an absolute-value case asserting `/tmp/custom-state` is preserved. Exercise both `cmd_apply()` and `cmd_uninstall()` with a fake `NiriIntegration` and assert they receive the same absolute state root when `XDG_STATE_HOME=""`.

- [ ] **Step 2: Add failing Bash lock-path tests**

Run `matugen-niri-apply` from two different temporary working directories with `XDG_STATE_HOME=""`, a fake blocking `flock`, and the same temporary `HOME`. Assert both invocations request exactly:

```text
$HOME/.local/state/matugen-theme-sync/niri.lock
```

Repeat with `XDG_STATE_HOME=relative-state` and assert the same fallback. Keep the existing absolute custom-state test valid.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_theme_sync_cli.NiriCommandTests \
  tests.test_niri_scripts.NiriApplyGenerationTests -v
```

Expected: failures show Python resolving empty/relative values from the working directory and Bash accepting a relative state path.

- [ ] **Step 4: Implement one rule in both entry points**

In `bin/matugen-theme-sync`, add:

```python
def resolve_state_home() -> Path:
    value = os.environ.get("XDG_STATE_HOME")
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
    return HOME / ".local/state"
```

Use it in both Niri apply and uninstall instead of constructing `Path(os.environ.get(...))` inline.

In `bin/matugen-niri-apply`, replace the current expansion with an absolute-path check:

```bash
case "${XDG_STATE_HOME-}" in
  /*) STATE_HOME="$XDG_STATE_HOME" ;;
  *) STATE_HOME="$HOME/.local/state" ;;
esac
```

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
python -m unittest tests.test_theme_sync_cli tests.test_niri_scripts -v
python -m unittest discover -s tests -v
bash -n bin/matugen-niri-apply
python -m py_compile bin/matugen-theme-sync
```

Expected: all pass.

- [ ] **Step 6: Commit canonical state resolution**

```bash
git add bin/matugen-theme-sync bin/matugen-niri-apply \
  tests/test_theme_sync_cli.py tests/test_niri_scripts.py
git commit -m "fix: canonicalize niri state paths"
```

---

### Task 2: Sync Generated Colors Before the Commit Journal

**Files:**
- Modify: `bin/niri_integration.py`
- Modify: `tests/test_niri_integration.py`

**Interfaces:**
- Produces: `_fsync_file(path: Path) -> None` and `_sync_generated_targets() -> None` on `NiriIntegration`.
- Preserves: `commit() -> str | None`, with the durable boundary still defined by publication of `committed-manifest.json`.

- [ ] **Step 1: Add a failing commit-order test**

Create all four generated targets, begin a transaction, and instrument `_fsync_file`, `_fsync_directory`, and `_atomic_write`. Call `commit()` and assert, for every generated target key:

```python
self.assertLess(events.index(f"file:{key}"), events.index("journal"))
self.assertLess(events.index(f"dir:{key}"), events.index("journal"))
```

The journal event is the `_atomic_write()` of `committed_manifest_path`. Assert the expected set is exactly `niri-colors`, `waybar-colors`, `rofi-colors`, and `mako-colors`.

- [ ] **Step 2: Add failing validation and fault tests**

Add tests proving:

- a missing generated target raises `IntegrationError` before the journal exists;
- a symlink or non-regular generated target is rejected before the journal;
- an injected `_fsync_file()` failure leaves no committed journal, keeps `transactions/current`, and allows `rollback()` to restore the pre-operation snapshot.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_niri_integration.NiriIntegrationTests.test_commit_syncs_generated_targets_before_publishing_journal \
  tests.test_niri_integration.NiriIntegrationTests.test_generated_sync_failure_remains_rollbackable -v
```

Expected: failures show no generated-file sync events before the journal.

- [ ] **Step 4: Implement the generated-target durability barrier**

Add a file sync helper that opens without following a managed symlink, verifies a regular file with `fstat`, and fsyncs the descriptor:

```python
@staticmethod
def _fsync_file(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise IntegrationError(f"managed target is not a regular file: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
```

Immediately before writing `committed-manifest.json`, iterate the `generated` targets in `TARGETS` order. Re-run `_assert_safe_targets()`, require each target to exist as a regular file, call `_fsync_file(target)`, then `_fsync_directory(target.parent)`. Only after all four barriers succeed may `commit()` publish the durable journal.

- [ ] **Step 5: Run focused and full tests**

Run:

```bash
python -m unittest tests.test_niri_integration -v
python -m unittest discover -s tests -v
python -m py_compile bin/niri_integration.py
git diff --check
```

Expected: all pass, including existing journal-last and lock tests.

- [ ] **Step 6: Commit the generated durability barrier**

```bash
git add bin/niri_integration.py tests/test_niri_integration.py
git commit -m "fix: sync generated niri colors before commit"
```

---

### Task 3: Recover Interrupted Apply Before Uninstall

**Files:**
- Modify: `bin/niri_integration.py`
- Modify: `tests/test_niri_integration.py`

**Interfaces:**
- Consumes: `_recover_transaction()` while `restore()` holds the lifecycle lock.
- Preserves: `restore() -> None`, immutable originals, conflicts, and idempotent retry.

- [ ] **Step 1: Add a failing leftover-current uninstall test**

Perform and commit an initial managed apply. Begin a second apply, mutate managed targets, then simulate process death by releasing/closing the lifecycle lock without rollback while leaving `transactions/current`. Construct a fresh manager and call `restore()`. Assert:

- the second apply is rolled back before uninstall logic runs;
- all original files are restored;
- `transactions/current`, `manifest.json`, and `originals/` are removed;
- conflict archives retain only genuine post-commit user divergence.

- [ ] **Step 2: Add the interrupted-uninstall reproducer as a failing test**

Use the same leftover `current`, then inject an exception immediately after the durable unlink of `manifest.json`. Assert the first restore had already removed `transactions/current`. Construct a new manager and call `begin()`; assert it snapshots the restored original bytes and never resurrects the managed pre-uninstall target or replaces the immutable original with managed bytes.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```bash
python -m unittest \
  tests.test_niri_integration.NiriIntegrationTests.test_restore_recovers_uncommitted_current_before_uninstall \
  tests.test_niri_integration.NiriIntegrationTests.test_interrupted_uninstall_cannot_resurrect_current_snapshot -v
```

Expected: the existing `current` survives until late cleanup and the injected retry can restore managed bytes.

- [ ] **Step 4: Recover before loading the uninstall manifest**

At the start of `_restore_locked()`, after `_assert_safe_targets()` and while the lifecycle lock is held, call:

```python
self._recover_transaction()
```

Remove the narrower committed-journal-only branch because `_recover_transaction()` already finalizes a committed journal, removes committed cleanup, or restores and removes an uncommitted `current` in the correct order. Load the manifest only after recovery completes.

- [ ] **Step 5: Run lifecycle and full verification**

Run:

```bash
python -m unittest tests.test_niri_integration -v
python -m unittest tests.test_theme_sync_cli -v
python -m unittest discover -s tests -v
bash -n bin/matugen-niri-apply bin/matugen-niri-watch install.sh
python -m py_compile bin/matugen-theme-sync bin/niri_integration.py
git diff --check
```

Expected: all pass. Re-run the real Matugen/Niri/Rofi/Mako validation test when the tools are installed.

- [ ] **Step 6: Commit interrupted-uninstall recovery**

```bash
git add bin/niri_integration.py tests/test_niri_integration.py
git commit -m "fix: recover niri transactions before uninstall"
```

---

## Final Review and Verification

- Review the fixed range from `6d18600` to the final HEAD against the three final-review residuals only.
- Run `python -m unittest discover -s tests -v`, shell syntax checks, Python compilation, `git diff --check`, `systemd-analyze --user verify systemd/matugen-niri.service`, and the conditional real-tool validation.
- Confirm `git status --short` still lists only the pre-existing unstaged GNOME/Plasma watcher edits outside committed follow-up work.
