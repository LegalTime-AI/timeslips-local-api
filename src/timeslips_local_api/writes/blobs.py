"""Copy Timeslips slip streams into new blobs.

Timeslips opens a description by the length stored in the stream. Reinserting
a template row's blob id, or a stream that could not be read to the end,
makes Slip Entry raise "The file is shorter than expected." A description
keeps the native magic and trailer and carries the full narrative.
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


# Observed on native unbilled SLPTRANS.DESCRIPTION blobs in the copy database.
# 47 0f 01 00 | uint16 length | uint16 length | text + NUL | 1e 00 01 00 00 00 00
NATIVE_DESCRIPTION_MAGIC = bytes.fromhex("470f0100")
NATIVE_DESCRIPTION_TRAILER = bytes.fromhex("1e000100000000")
_MAX_DESCRIPTION_BYTES = 65535


def _native_parts(blob: bytes) -> tuple[bytes, int, bytes, bytes] | None:
    """Return (magic, length, payload, trailer) for a Timeslips description stream."""
    if len(blob) < 4 + 2 + 2 + len(NATIVE_DESCRIPTION_TRAILER):
        return None
    if not blob.startswith(NATIVE_DESCRIPTION_MAGIC):
        return None
    length = int.from_bytes(blob[4:6], "little")
    length_again = int.from_bytes(blob[6:8], "little")
    if length != length_again or length > _MAX_DESCRIPTION_BYTES:
        return None
    payload_end = 8 + length
    if payload_end + len(NATIVE_DESCRIPTION_TRAILER) != len(blob):
        return None
    trailer = blob[payload_end:]
    if trailer != NATIVE_DESCRIPTION_TRAILER:
        return None
    return blob[:4], length, blob[8:payload_end], trailer


def decode_slip_description(value: Any) -> str:
    """Return the narrative Timeslips stored, without the stream framing."""
    blob = read_blob(value)
    if not blob:
        return ""
    native = _native_parts(blob)
    if native is not None:
        _magic, _length, payload, _trailer = native
        if payload.endswith(b"\x00"):
            payload = payload[:-1]
        return payload.decode("cp1252", errors="replace")
    if b"\x00" not in blob:
        return blob.decode("cp1252", errors="replace")
    return blob.decode("utf-8", errors="replace")


def encode_slip_description(template: bytes, text: str) -> bytes:
    """Write the full slip narrative in the native Timeslips description stream.

    Both length words count the text plus its trailing NUL. The magic and
    trailer stay the bytes Timeslips already uses, including when the new
    text is longer or shorter than the template.
    """
    raw = (text or "").encode("cp1252", errors="replace")
    if len(raw) + 1 > _MAX_DESCRIPTION_BYTES:
        raw = raw[: _MAX_DESCRIPTION_BYTES - 1]
    payload = raw + b"\x00"
    length = len(payload)
    magic = NATIVE_DESCRIPTION_MAGIC
    trailer = NATIVE_DESCRIPTION_TRAILER
    native = _native_parts(template)
    if native is not None:
        magic, _length, _payload, trailer = native
    words = length.to_bytes(2, "little")
    return magic + words + words + payload + trailer


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
