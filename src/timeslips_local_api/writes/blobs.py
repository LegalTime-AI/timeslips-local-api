"""Copy Timeslips slip streams into new blobs.

Timeslips opens description and other SLPTRANS streams by length. Reinserting
a template row's blob id, or a stream that could not be read to the end,
makes Slip Entry raise "The file is shorter than expected."
"""

from __future__ import annotations

from typing import Any

# firebirdsql reports blobs as SQL_TYPE_BLOB (520). 261 is the older BLR code.
SQL_BLOB = 520
BLOB_TYPE_CODES = frozenset({520, 261})


def field_type_code(description_item: tuple) -> int | None:
    if len(description_item) < 2 or not isinstance(description_item[1], int):
        return None
    return description_item[1] & ~1


def read_blob(value: Any) -> bytes | None:
    """Return the full stream. A blob id cannot be read, so it is refused."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, int):
        return None
    reader = getattr(value, "read", None)
    if not callable(reader):
        return None
    try:
        data = reader()
    except Exception:
        return None
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, bytes):
        return data
    return None


def _is_blob(code: int | None) -> bool:
    if code is None:
        return False
    return code in BLOB_TYPE_CODES or (code & ~1) in BLOB_TYPE_CODES


def _looks_utf16(blob: bytes) -> bool:
    if len(blob) < 4 or len(blob) % 2:
        return False
    return blob[1::2].count(0) >= len(blob) // 4


def _framed_text(blob: bytes) -> tuple[str, int, bytes] | None:
    """Return (kind, width, header) when the blob is a length plus text."""
    if not blob:
        return None
    if blob.startswith(b"\xff\xfe") and _looks_utf16(blob[2:]):
        return ("bom-utf16", 0, b"\xff\xfe")
    limit = min(16, max(0, len(blob) - 2))
    for start in range(limit):
        for width, kind in ((4, "u32"), (2, "u16")):
            if start + width > len(blob):
                continue
            count = int.from_bytes(blob[start : start + width], "little")
            rest = blob[start + width :]
            header = blob[:start]
            if count > 0 and count == len(rest):
                return (f"{kind}-bytes", width, header)
            if count > 0 and count * 2 == len(rest):
                return (f"{kind}-utf16", width, header)
    return None


def _printable_runs(blob: bytes) -> list[tuple[int, int, str, str]]:
    """Locate human text inside a native Timeslips stream."""
    runs: list[tuple[int, int, str, str]] = []
    origins = [2] if blob.startswith(b"\xff\xfe") else [0, 1]
    for origin in origins:
        index = origin
        while index + 1 < len(blob):
            chars: list[str] = []
            start = index
            while index + 1 < len(blob):
                code = int.from_bytes(blob[index : index + 2], "little")
                if code in (9, 10, 13) or 32 <= code < 127:
                    chars.append(chr(code))
                    index += 2
                    continue
                break
            if len(chars) >= 4:
                runs.append((start, index, "".join(chars), "utf-16le"))
            index = start + 2
    index = 0
    while index < len(blob):
        chars = []
        start = index
        while index < len(blob) and (blob[index] in (9, 10, 13) or 32 <= blob[index] < 127):
            chars.append(chr(blob[index]))
            index += 1
        if len(chars) >= 4:
            runs.append((start, index, "".join(chars), "cp1252"))
        index = start + 1
    return runs


def _patch_length(blob: bytearray, start: int, old_len: int, new_len: int, old_chars: int, new_chars: int) -> None:
    for width in (4, 2, 1):
        if start < width:
            continue
        count = int.from_bytes(blob[start - width : start], "little")
        if count == old_len:
            blob[start - width : start] = new_len.to_bytes(width, "little")
            return
        if count == old_chars:
            blob[start - width : start] = new_chars.to_bytes(width, "little")
            return


def _fit_encoded(text: str, size: int, encoding: str) -> bytes:
    raw = text.encode(encoding)
    if encoding == "utf-16le":
        size -= size % 2
        raw = raw[:size]
        pad = b"\x20\x00" * ((size - len(raw)) // 2)
        return raw + pad
    raw = raw[:size]
    return raw + b" " * (size - len(raw))


def encode_slip_description(template: bytes, text: str) -> bytes:
    """Keep the native stream byte-for-byte and replace only its text.

    Changing the stream length makes Slip Entry report an unknown object.
    The replacement stays the same size as the words already in the template.
    """
    text = text or ""
    if not template:
        return text.encode("cp1252", errors="replace")
    runs = _printable_runs(template)
    if not runs:
        return template
    start, end, old, encoding = max(runs, key=lambda run: len(run[2]))
    if not old.strip():
        return template
    new_bytes = _fit_encoded(text, end - start, encoding)
    return template[:start] + new_bytes + template[end:]


def rewrite_slip_blobs(
    row: dict,
    columns: list[tuple[str, int | None]],
    description: str | None,
    template_description: Any = None,
) -> None:
    """Replace every blob with bytes this process owns. Never keep a blob id."""
    for name, code in columns:
        if not _is_blob(code):
            continue
        if name == "DESCRIPTION" and description is not None:
            source = template_description if template_description is not None else row.get(name)
            template = read_blob(source) or b""
            row[name] = encode_slip_description(template, description)
            continue
        copied = read_blob(row.get(name))
        row[name] = copied if copied is not None else b""
