from timeslips_local_api.writes.blobs import (
    SQL_BLOB,
    encode_slip_description,
    read_blob,
    rewrite_slip_blobs,
)


class _Boom:
    def read(self) -> bytes:
        raise OSError("short read")


class _Stream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


def test_firebird_blob_columns_keep_the_full_time_entry() -> None:
    description = "Reviewed the trust file and sent the letter."
    row = {
        "RECORDID": 1506,
        "USERID": 12,
        "CLIENTID": 44,
        "ACTYEXPID": 7,
        "TIMESPENT": 600,
        "DESCRIPTION": 42,
        "CUSTOMTEXT": 99,
        "NOTES": _Stream(b"native-notes-complete"),
        "RATEVALUE": 595,
    }
    columns = [
        ("RECORDID", 496),
        ("USERID", 496),
        ("CLIENTID", 496),
        ("ACTYEXPID", 496),
        ("TIMESPENT", 496),
        ("DESCRIPTION", SQL_BLOB),
        ("CUSTOMTEXT", 261),
        ("NOTES", SQL_BLOB | 1),
        ("RATEVALUE", 480),
    ]
    template = "Old note".encode("utf-16le")
    template = len("Old note").to_bytes(4, "little") + template
    row["DESCRIPTION"] = template
    rewrite_slip_blobs(row, columns, description, template)
    assert row["DESCRIPTION"] == len(description).to_bytes(4, "little") + description.encode("utf-16le")
    assert row["CUSTOMTEXT"] == b""
    assert row["NOTES"] == b"native-notes-complete"
    assert row["USERID"] == 12
    assert row["CLIENTID"] == 44
    assert row["ACTYEXPID"] == 7
    assert row["TIMESPENT"] == 600
    assert row["RATEVALUE"] == 595
    assert read_blob(_Boom()) is None


def test_description_keeps_a_length_prefix_instead_of_plain_utf8() -> None:
    text = "Reviewed the trust file."
    encoded = encode_slip_description(b"", text)
    assert encoded != text.encode("utf-8")
    assert int.from_bytes(encoded[:4], "little") == len(text)
    assert encoded[4:] == text.encode("utf-16le")
