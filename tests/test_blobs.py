from timeslips_local_api.writes.blobs import SQL_BLOB, read_blob, rewrite_slip_blobs


class _Boom:
    def read(self) -> bytes:
        raise OSError("short read")


class _Stream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


def test_blob_ids_are_not_reused_and_description_is_rewritten() -> None:
    row = {
        "DESCRIPTION": 42,
        "CUSTOMTEXT": 99,
        "NOTES": _Stream(b"native-notes"),
        "RATEVALUE": 595,
    }
    columns = [
        ("DESCRIPTION", SQL_BLOB),
        ("CUSTOMTEXT", SQL_BLOB),
        ("NOTES", SQL_BLOB),
        ("RATEVALUE", 8),
    ]
    rewrite_slip_blobs(row, columns, "Reviewed the file.")
    assert row["DESCRIPTION"] == b"Reviewed the file."
    assert row["CUSTOMTEXT"] == b""
    assert row["NOTES"] == b"native-notes"
    assert row["RATEVALUE"] == 595
    assert read_blob(_Boom()) is None
