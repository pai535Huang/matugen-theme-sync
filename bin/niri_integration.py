#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


NIRI_BEGIN = "// BEGIN MATUGEN THEME SYNC"
NIRI_END = "// END MATUGEN THEME SYNC"
ROFI_BEGIN = "/* BEGIN MATUGEN THEME SYNC */"
ROFI_END = "/* END MATUGEN THEME SYNC */"

NIRI_BODY = 'include "./colors.kdl"'
ROFI_BODY = '@theme "matugen"'

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

STATIC_SOURCES = {
    "waybar-style": "waybar/style.css",
    "rofi-theme": "rofi/matugen.rasi",
    "mako-config": "mako/config",
}

INHERITED_LOCK_FD_ENV = "MATUGEN_NIRI_INHERITED_LOCK_FD"


class ManagedBlockError(RuntimeError):
    """Raised when a managed configuration block cannot be edited safely."""


def _block_pattern(begin: str, end: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^{re.escape(begin)}\n.*?^{re.escape(end)}\n?",
        re.DOTALL,
    )


def _validate_markers(text: str, begin: str, end: str) -> int:
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != end_count or begin_count > 1:
        raise ManagedBlockError("managed theme markers are partial or duplicated")
    if begin_count and _block_pattern(begin, end).search(text) is None:
        raise ManagedBlockError("managed theme markers are malformed")
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


class IntegrationError(RuntimeError):
    """Raised when managed theme deployment cannot complete safely."""


class DurableCommitError(OSError):
    """Raised when a durable commit needs a later recovery attempt."""


class NiriIntegration:
    def __init__(
        self,
        home: Path,
        state_home: Path,
        resources: Path,
        timestamp: Callable[[], str] | None = None,
    ):
        self.home = Path(home)
        self.root = Path(state_home) / "matugen-theme-sync/niri"
        self.resources = Path(resources)
        self.timestamp = timestamp or (
            lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
        self.transaction = self.root / "transactions/current"
        self._lock_descriptor: int | None = None

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def committed_manifest_path(self) -> Path:
        return self.root / "transactions/committed-manifest.json"

    @property
    def committed_cleanup_path(self) -> Path:
        return self.root / "transactions/committed-cleanup"

    @property
    def lock_path(self) -> Path:
        return self.root.parent / "niri.lock"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_file(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise IntegrationError(
                    f"managed target is not a regular file: {path}"
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _durable_mkdir(cls, path: Path) -> None:
        path = Path(path)
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            parent = current.parent
            if parent == current:
                raise OSError(f"cannot find an existing parent for {path}")
            current = parent
        if not current.is_dir():
            raise NotADirectoryError(current)
        for directory in reversed(missing):
            try:
                os.mkdir(directory)
            except FileExistsError:
                if not directory.is_dir():
                    raise
            else:
                cls._fsync_directory(directory.parent)

    @classmethod
    def _durable_replace(cls, source: Path, destination: Path) -> None:
        source = Path(source)
        destination = Path(destination)
        cls._durable_mkdir(destination.parent)
        os.replace(source, destination)
        cls._fsync_directory(destination.parent)
        if source.parent != destination.parent:
            cls._fsync_directory(source.parent)

    @classmethod
    def _durable_unlink(cls, path: Path, *, missing_ok: bool = False) -> None:
        path = Path(path)
        try:
            path.unlink()
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        cls._fsync_directory(path.parent)

    @classmethod
    def _durable_rmtree(cls, path: Path) -> None:
        path = Path(path)
        shutil.rmtree(path)
        cls._fsync_directory(path.parent)

    @classmethod
    def _atomic_write(cls, path: Path, data: str | bytes, mode: int = 0o644) -> None:
        cls._durable_mkdir(path.parent)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}."
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fchmod(stream.fileno(), mode)
                os.fsync(stream.fileno())
            cls._durable_replace(temporary, path)
        finally:
            if temporary.exists():
                cls._durable_unlink(temporary)

    def _acquire_lifecycle_lock(self) -> None:
        if self._lock_descriptor is not None:
            raise IntegrationError("managed theme lifecycle lock is already held")
        self._durable_mkdir(self.lock_path.parent)
        existed = self.lock_path.exists()
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if not existed:
                self._fsync_directory(self.lock_path.parent)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except BaseException:
            os.close(descriptor)
            raise
        self._lock_descriptor = descriptor

    def _release_lifecycle_lock(self) -> None:
        descriptor = self._lock_descriptor
        if descriptor is None:
            return
        self._lock_descriptor = None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def bootstrap_subprocess_kwargs(
        self, environment: Mapping[str, str] | None = None
    ) -> dict[str, object]:
        descriptor = self._lock_descriptor
        if descriptor is None:
            raise IntegrationError("managed theme lifecycle lock is not held")
        child_environment = dict(os.environ if environment is None else environment)
        child_environment[INHERITED_LOCK_FD_ENV] = str(descriptor)
        return {"env": child_environment, "pass_fds": (descriptor,)}

    def _target_path(self, key: str) -> Path:
        return self.home / TARGETS[key][0]

    def _assert_safe_targets(self) -> None:
        for relative, _ in TARGETS.values():
            component = self.home
            if component.is_symlink():
                raise IntegrationError(f"managed path is a symlink: {component}")
            for part in Path(relative).parts:
                component /= part
                if component.is_symlink():
                    raise IntegrationError(f"managed path is a symlink: {component}")
                if not component.exists():
                    break

    def _sync_generated_targets(self) -> None:
        self._assert_safe_targets()
        for key, (_, kind) in TARGETS.items():
            if kind != "generated":
                continue
            target = self._target_path(key)
            if not target.exists() or not target.is_file():
                raise IntegrationError(
                    f"managed target is not a regular file: {target}"
                )
            self._fsync_file(target)
            self._fsync_directory(target.parent)

    def _snapshot_target(self, key: str, directory: Path) -> dict[str, object]:
        target = self._target_path(key)
        if not target.exists():
            return {"exists": False}
        if not target.is_file():
            raise IntegrationError(f"managed target is not a regular file: {target}")
        mode = stat.S_IMODE(target.stat().st_mode)
        self._atomic_write(directory / key, target.read_bytes(), mode)
        return {"exists": True, "mode": mode}

    def _restore_snapshot(self, directory: Path) -> None:
        metadata_path = directory / "metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise IntegrationError("transaction snapshot is incomplete") from error
        if set(metadata) != set(TARGETS):
            raise IntegrationError("transaction snapshot does not cover all targets")
        for key in TARGETS:
            target = self._target_path(key)
            entry = metadata[key]
            if entry.get("exists"):
                snapshot = directory / key
                if not snapshot.is_file():
                    raise IntegrationError(f"transaction snapshot is missing {key}")
                self._atomic_write(target, snapshot.read_bytes(), int(entry["mode"]))
            elif target.exists():
                if not target.is_file() and not target.is_symlink():
                    raise IntegrationError(f"managed target is not a file: {target}")
                self._durable_unlink(target)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, object]:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise IntegrationError("managed theme manifest is unreadable") from error
        if manifest.get("version") != 1 or not isinstance(
            manifest.get("targets"), dict
        ):
            raise IntegrationError("managed theme manifest has an unsupported format")
        return manifest

    def _load_manifest(self) -> dict[str, object]:
        if not self.manifest_path.exists():
            return {"version": 1, "targets": {}}
        return self._read_manifest(self.manifest_path)

    def _write_manifest(self, manifest: dict[str, object]) -> None:
        self._atomic_write(
            self.manifest_path,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )

    def _create_original(self, key: str) -> dict[str, object]:
        target = self._target_path(key)
        _, kind = TARGETS[key]
        entry: dict[str, object] = {
            "path": str(target),
            "kind": kind,
            "original_exists": target.exists(),
        }
        if target.exists():
            if not target.is_file():
                raise IntegrationError(
                    f"managed target is not a regular file: {target}"
                )
            mode = stat.S_IMODE(target.stat().st_mode)
            self._atomic_write(self.root / "originals" / key, target.read_bytes(), mode)
            entry["original_mode"] = mode
        return entry

    def _require_transaction(self) -> None:
        if not self.transaction.is_dir():
            raise IntegrationError("no managed theme transaction is active")

    def _finalize_committed_transaction(self) -> None:
        manifest = self._read_manifest(self.committed_manifest_path)
        self._write_manifest(manifest)
        if self.committed_cleanup_path.exists():
            if not self.committed_cleanup_path.is_dir():
                raise IntegrationError("committed cleanup path is not a directory")
            self._durable_rmtree(self.committed_cleanup_path)
        if self.transaction.exists():
            if not self.transaction.is_dir():
                raise IntegrationError("transaction path is not a directory")
            self._durable_replace(self.transaction, self.committed_cleanup_path)
        if self.committed_cleanup_path.exists():
            self._durable_rmtree(self.committed_cleanup_path)
        # A prior attempt may have removed cleanup but failed while syncing its
        # parent. Re-sync before the recovery journal can disappear.
        self._fsync_directory(self.committed_manifest_path.parent)
        self._durable_unlink(self.committed_manifest_path)

    def _recover_transaction(self) -> None:
        if self.committed_manifest_path.is_file():
            self._finalize_committed_transaction()
            return
        if self.committed_cleanup_path.exists():
            if not self.committed_cleanup_path.is_dir():
                raise IntegrationError("committed cleanup path is not a directory")
            self._durable_rmtree(self.committed_cleanup_path)
        if not self.transaction.exists():
            return
        if not self.transaction.is_dir():
            raise IntegrationError("transaction path is not a directory")
        self._restore_snapshot(self.transaction)
        self._durable_rmtree(self.transaction)

    def begin(self) -> None:
        self._acquire_lifecycle_lock()
        try:
            self._assert_safe_targets()
            self._recover_transaction()

            manifest = self._load_manifest()
            targets = manifest["targets"]
            for key in TARGETS:
                if key not in targets:
                    targets[key] = self._create_original(key)
            self._write_manifest(manifest)

            transactions = self.root / "transactions"
            preparing = transactions / "preparing"
            if preparing.exists():
                self._durable_rmtree(preparing)
            self._durable_mkdir(preparing)
            metadata = {
                key: self._snapshot_target(key, preparing) for key in TARGETS
            }
            self._atomic_write(
                preparing / "metadata.json",
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            )
            self._durable_replace(preparing, self.transaction)
        except BaseException:
            self._release_lifecycle_lock()
            raise

    def _render_static(self, key: str, source: str) -> str:
        replacements = {
            "@MATUGEN_WAYBAR_COLORS@": str(
                self.home / ".config/waybar/colors.css"
            ),
            "@MATUGEN_MAKO_COLORS@": str(self.home / ".config/mako/colors"),
        }
        for marker, value in replacements.items():
            source = source.replace(marker, value)
        if "@MATUGEN_" in source:
            raise IntegrationError(f"unresolved deployment marker in {key}")
        return source

    def _archive(self, key: str, target: Path) -> None:
        archive = self.root / "conflicts" / self.timestamp() / key
        if archive.exists():
            if (
                self._sha256(archive) == self._sha256(target)
                and stat.S_IMODE(archive.stat().st_mode)
                == stat.S_IMODE(target.stat().st_mode)
            ):
                return
            sequence = 1
            while archive.with_name(f"{key}.{sequence}").exists():
                sequence += 1
            archive = archive.with_name(f"{key}.{sequence}")
        self._atomic_write(
            archive,
            target.read_bytes(),
            stat.S_IMODE(target.stat().st_mode),
        )

    def _archive_absent(self, key: str) -> None:
        archive = self.root / "conflicts" / self.timestamp() / f"{key}.absent"
        if archive.exists():
            return
        self._atomic_write(archive, b"", 0o644)

    def _archive_if_changed(
        self, key: str, target: Path, entry: dict[str, object]
    ) -> None:
        if not target.exists():
            if entry.get("deployed_checksum") or entry.get("original_exists"):
                self._archive_absent(key)
            return
        if not target.is_file():
            raise IntegrationError(f"managed target is not a regular file: {target}")
        deployed = entry.get("deployed_checksum")
        if deployed:
            changed = self._sha256(target) != deployed
        elif entry.get("original_exists"):
            original = self.root / "originals" / key
            if not original.is_file():
                raise IntegrationError(f"original snapshot is missing {key}")
            changed = (
                self._sha256(target) != self._sha256(original)
                or stat.S_IMODE(target.stat().st_mode)
                != int(entry["original_mode"])
            )
        else:
            changed = True
        if changed:
            self._archive(key, target)

    def deploy_static(self) -> None:
        self._assert_safe_targets()
        self._require_transaction()
        rendered = {}
        for key, relative in STATIC_SOURCES.items():
            source_path = self.resources / relative
            try:
                source = source_path.read_text(encoding="utf-8")
            except OSError as error:
                raise IntegrationError(
                    f"static resource is unavailable: {relative}"
                ) from error
            rendered[key] = self._render_static(key, source)

        manifest = self._load_manifest()
        for key, source in rendered.items():
            target = self._target_path(key)
            entry = manifest["targets"][key]
            self._archive_if_changed(key, target, entry)
            source_path = self.resources / STATIC_SOURCES[key]
            mode = (
                stat.S_IMODE(target.stat().st_mode)
                if target.exists()
                else stat.S_IMODE(source_path.stat().st_mode)
            )
            self._atomic_write(target, source, mode)

    def activate(self) -> None:
        self._assert_safe_targets()
        self._require_transaction()
        manifest = self._load_manifest()
        blocks = {
            "niri-config": (NIRI_BEGIN, NIRI_END, NIRI_BODY),
            "rofi-config": (ROFI_BEGIN, ROFI_END, ROFI_BODY),
        }
        for key, (begin, end, body) in blocks.items():
            target = self._target_path(key)
            entry = manifest["targets"][key]
            if target.exists() and not target.is_file():
                raise IntegrationError(
                    f"managed target is not a regular file: {target}"
                )
            self._archive_if_changed(key, target, entry)
            if target.exists():
                current = target.read_text(encoding="utf-8")
                mode = stat.S_IMODE(target.stat().st_mode)
            else:
                current = ""
                mode = 0o644
            try:
                updated = upsert_managed_block(current, begin, end, body)
            except ManagedBlockError as error:
                raise IntegrationError(f"cannot update malformed {key}") from error
            self._atomic_write(target, updated, mode)

    def commit(self) -> str | None:
        try:
            self._assert_safe_targets()
            self._require_transaction()
            manifest = self._load_manifest()
            transaction_metadata = json.loads(
                (self.transaction / "metadata.json").read_text(encoding="utf-8")
            )
            for key, (_, kind) in TARGETS.items():
                if kind not in {"static", "patched"}:
                    continue
                target = self._target_path(key)
                entry = manifest["targets"][key]
                entry["deployed_checksum"] = (
                    self._sha256(target) if target.is_file() else None
                )
                if (
                    kind == "patched"
                    and entry.get("original_exists")
                    and not transaction_metadata[key].get("exists")
                ):
                    entry["restore_original_on_uninstall"] = True
            self._sync_generated_targets()
            self._atomic_write(
                self.committed_manifest_path,
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
            try:
                self._finalize_committed_transaction()
            except (OSError, IntegrationError) as initial_error:
                try:
                    self._finalize_committed_transaction()
                except (OSError, IntegrationError) as recovery_error:
                    raise DurableCommitError(
                        "durable commit is pending recovery; the deployment "
                        f"must not be rolled back: {recovery_error}"
                    ) from recovery_error
                return f"durable commit recovered after: {initial_error}"
            return None
        finally:
            self._release_lifecycle_lock()

    def rollback(self) -> None:
        try:
            self._assert_safe_targets()
            if self.committed_manifest_path.is_file():
                self._finalize_committed_transaction()
                return
            self._require_transaction()
            self._restore_snapshot(self.transaction)
            self._durable_rmtree(self.transaction)
        finally:
            self._release_lifecycle_lock()

    def _restore_original(self, key: str, entry: dict[str, object]) -> None:
        target = self._target_path(key)
        if entry.get("original_exists"):
            original = self.root / "originals" / key
            if not original.is_file():
                raise IntegrationError(f"original snapshot is missing {key}")
            self._atomic_write(
                target, original.read_bytes(), int(entry["original_mode"])
            )
        elif target.exists():
            if not target.is_file() and not target.is_symlink():
                raise IntegrationError(f"managed target is not a file: {target}")
            self._durable_unlink(target)

    def restore(self) -> None:
        self._acquire_lifecycle_lock()
        try:
            self._restore_locked()
        finally:
            self._release_lifecycle_lock()

    def _restore_locked(self) -> None:
        self._assert_safe_targets()
        if self.committed_manifest_path.is_file():
            self._finalize_committed_transaction()
        manifest = self._load_manifest()
        targets = manifest["targets"]
        if not targets:
            return

        blocks = {
            "niri-config": (NIRI_BEGIN, NIRI_END),
            "rofi-config": (ROFI_BEGIN, ROFI_END),
        }
        for key, (begin, end) in blocks.items():
            entry = targets[key]
            target = self._target_path(key)
            if entry.get("restore_original_on_uninstall"):
                self._archive_if_changed(key, target, entry)
                self._restore_original(key, entry)
                continue
            if not target.exists():
                if entry.get("original_exists"):
                    self._archive_absent(key)
                    self._restore_original(key, entry)
                continue
            if not target.is_file():
                raise IntegrationError(
                    f"managed target is not a regular file: {target}"
                )
            current = target.read_text(encoding="utf-8")
            try:
                restored = remove_managed_block(current, begin, end)
            except ManagedBlockError:
                self._archive(key, target)
                self._restore_original(key, entry)
                continue
            self._archive_if_changed(key, target, entry)
            if not entry.get("original_exists") and not restored.strip():
                self._durable_unlink(target)
            else:
                self._atomic_write(
                    target, restored, stat.S_IMODE(target.stat().st_mode)
                )

        for key, (_, kind) in TARGETS.items():
            if kind == "patched":
                continue
            entry = targets[key]
            target = self._target_path(key)
            if kind == "static":
                self._archive_if_changed(key, target, entry)
            self._restore_original(key, entry)

        if self.manifest_path.exists():
            self._durable_unlink(self.manifest_path)
        originals = self.root / "originals"
        transactions = self.root / "transactions"
        if originals.exists():
            self._durable_rmtree(originals)
        if transactions.exists():
            self._durable_rmtree(transactions)

    def validate(self, run: Callable) -> None:
        commands = (
            ["niri", "validate", "-c", str(self.home / ".config/niri/config.kdl")],
            [
                "rofi",
                "-no-config",
                "-theme",
                str(self.home / ".config/rofi/themes/matugen.rasi"),
                "-dump-theme",
            ],
            ["mako", "-c", str(self.home / ".config/mako/config")],
        )
        for command in commands:
            if shutil.which(command[0]) is None:
                continue
            if command[0] != "mako":
                result = run(command, capture_output=True, text=True)
                if result.returncode == 0 and "Failed to parse config" not in result.stderr:
                    continue
                raise IntegrationError(
                    f"configuration validation failed: {command[0]}"
                )

            environment = os.environ.copy()
            environment.pop("DISPLAY", None)
            environment["WAYLAND_DISPLAY"] = "matugen-theme-sync-invalid"
            environment["DBUS_SESSION_BUS_ADDRESS"] = (
                f"unix:path={self.root.parent / 'validation-no-bus'}"
            )
            try:
                result = run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env=environment,
                )
            except subprocess.TimeoutExpired:
                # Mako parsed the file and stayed alive until the bounded
                # isolated-session probe terminated it.
                continue
            diagnostic = (
                f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
            ).lower()
            if "failed to parse" in diagnostic or "[config:" in diagnostic:
                raise IntegrationError("configuration validation failed: mako")
            if result.returncode == 0:
                continue
            expected_connection_failures = (
                "failed to connect to user bus",
                "failed to connect to wayland",
                "failed to connect to display",
            )
            if any(message in diagnostic for message in expected_connection_failures):
                continue
            raise IntegrationError("configuration validation failed: mako")

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
