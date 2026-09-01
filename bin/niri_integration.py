#!/usr/bin/env python3
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


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

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _atomic_write(path: Path, data: str | bytes, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.encode("utf-8") if isinstance(data, str) else data
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}."
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _target_path(self, key: str) -> Path:
        return self.home / TARGETS[key][0]

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
                target.unlink()

    def _load_manifest(self) -> dict[str, object]:
        if not self.manifest_path.exists():
            return {"version": 1, "targets": {}}
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise IntegrationError("managed theme manifest is unreadable") from error
        if manifest.get("version") != 1 or not isinstance(
            manifest.get("targets"), dict
        ):
            raise IntegrationError("managed theme manifest has an unsupported format")
        return manifest

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

    def begin(self) -> None:
        if self.transaction.exists():
            if not self.transaction.is_dir():
                raise IntegrationError("transaction path is not a directory")
            self._restore_snapshot(self.transaction)
            shutil.rmtree(self.transaction)

        manifest = self._load_manifest()
        targets = manifest["targets"]
        for key in TARGETS:
            if key not in targets:
                targets[key] = self._create_original(key)
        self._write_manifest(manifest)

        transactions = self.root / "transactions"
        preparing = transactions / "preparing"
        if preparing.exists():
            shutil.rmtree(preparing)
        preparing.mkdir(parents=True)
        metadata = {key: self._snapshot_target(key, preparing) for key in TARGETS}
        self._atomic_write(
            preparing / "metadata.json",
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        )
        os.replace(preparing, self.transaction)

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
            if self._sha256(archive) == self._sha256(target):
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

    def _archive_if_changed(
        self, key: str, target: Path, entry: dict[str, object]
    ) -> None:
        deployed = entry.get("deployed_checksum")
        if deployed and target.exists() and self._sha256(target) != deployed:
            self._archive(key, target)

    def deploy_static(self) -> None:
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
            if target.exists():
                self._archive_if_changed(key, target, entry)
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

    def commit(self) -> None:
        self._require_transaction()
        manifest = self._load_manifest()
        for key, (_, kind) in TARGETS.items():
            if kind not in {"static", "patched"}:
                continue
            target = self._target_path(key)
            manifest["targets"][key]["deployed_checksum"] = (
                self._sha256(target) if target.is_file() else None
            )
        self._write_manifest(manifest)
        shutil.rmtree(self.transaction)

    def rollback(self) -> None:
        self._require_transaction()
        self._restore_snapshot(self.transaction)
        shutil.rmtree(self.transaction)

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
            target.unlink()

    def restore(self) -> None:
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
            if not target.exists():
                if entry.get("original_exists"):
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
                target.unlink()
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
            self.manifest_path.unlink()
        originals = self.root / "originals"
        transactions = self.root / "transactions"
        if originals.exists():
            shutil.rmtree(originals)
        if transactions.exists():
            shutil.rmtree(transactions)

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
            ["mako", "-c", str(self.home / ".config/mako/config"), "--help"],
        )
        for command in commands:
            if shutil.which(command[0]) is None:
                continue
            result = run(command, capture_output=True, text=True)
            if result.returncode != 0 or "Failed to parse config" in result.stderr:
                raise IntegrationError(
                    f"configuration validation failed: {command[0]}"
                )

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
