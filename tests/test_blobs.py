from timeslips_local_api.writes.blobs import (
    SQL_BLOB,
    decode_slip_description,
    encode_slip_description,
    read_blob,
    rewrite_slip_blobs,
)

DAVID = "Review email from David requesting PDFs of new Wills; send with reply."
DAVID_BLOB = bytes.fromhex(
    "470f010047004700"
    + DAVID.encode("cp1252").hex()
    + "00"
    + "1e000100000000"
)
EMPTY_BLOB = bytes.fromhex("470f010001000100001e000100000000")


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
    rewrite_slip_blobs(row, columns, description, DAVID_BLOB)
    assert decode_slip_description(row["DESCRIPTION"]) == description
    assert row["DESCRIPTION"].startswith(bytes.fromhex("470f0100"))
    assert row["DESCRIPTION"].endswith(bytes.fromhex("1e000100000000"))
    assert row["CUSTOMTEXT"] == b""
    assert row["NOTES"] == b"native-notes-complete"
    assert row["USERID"] == 12
    assert row["CLIENTID"] == 44
    assert row["ACTYEXPID"] == 7
    assert row["TIMESPENT"] == 600
    assert row["RATEVALUE"] == 595
    assert read_blob(_Boom()) is None


def test_description_frame_keeps_full_text_at_its_own_length() -> None:
    text = "Reviewed the trust file and prepared a longer slip narrative for Timeslips."
    encoded = encode_slip_description(DAVID_BLOB, text)
    payload = text.encode("cp1252") + b"\x00"
    assert encoded.startswith(bytes.fromhex("470f0100"))
    assert encoded.endswith(bytes.fromhex("1e000100000000"))
    assert encoded[4:6] == len(payload).to_bytes(2, "little")
    assert encoded[6:8] == encoded[4:6]
    assert encoded[8 : 8 + len(payload)] == payload
    assert len(encoded) != len(DAVID_BLOB)
    assert decode_slip_description(encoded) == text


def test_native_and_plain_descriptions_decode() -> None:
    assert decode_slip_description(DAVID_BLOB) == DAVID
    assert decode_slip_description(EMPTY_BLOB) == ""
    plain = b"timeslips-local-api GUI check 2026-09-20 unbilled time slip"
    assert decode_slip_description(plain) == plain.decode("cp1252")
    assert encode_slip_description(b"", "") == EMPTY_BLOB


class _Boom:
    def read(self) -> bytes:
        raise OSError("short read")


class _Stream:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload
