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


def encode_slip_description(template: bytes, text: str) -> bytes:
    """Write slip text in the same shape Timeslips already stored.

    Plain UTF-8 makes Slip Entry treat the first bytes as a length and then
    report that the stream is shorter than that length. Only our slips fail.
    """
    text = text or ""
    framed = _framed_text(template)
    if framed is not None:
        kind, width, header = framed
        if kind == "bom-utf16":
            return b"\xff\xfe" + text.encode("utf-16le")
        if kind.endswith("-utf16"):
            encoded = text.encode("utf-16le")
            return header + len(text).to_bytes(width, "little") + encoded
        encoded = text.encode("cp1252", errors="replace")
        return header + len(encoded).to_bytes(width, "little") + encoded
    if _looks_utf16(template):
        return text.encode("utf-16le")
    encoded = text.encode("utf-16le")
    return len(text).to_bytes(4, "little") + encoded


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
