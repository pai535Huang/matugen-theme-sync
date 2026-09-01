#!/usr/bin/env python3
import re


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
