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


def rewrite_slip_blobs(
    row: dict,
    columns: list[tuple[str, int | None]],
    description: str | None,
) -> None:
    """Replace every blob with bytes this process owns. Never keep a blob id."""
    for name, code in columns:
        if code is None or (code not in BLOB_TYPE_CODES and (code & ~1) not in BLOB_TYPE_CODES):
            continue
        if name == "DESCRIPTION" and description is not None:
            row[name] = description.encode("utf-8")
            continue
        copied = read_blob(row.get(name))
        row[name] = copied if copied is not None else b""
