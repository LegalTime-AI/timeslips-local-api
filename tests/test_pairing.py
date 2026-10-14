import pytest

from timeslips_local_api.errors import ApiError
from timeslips_local_api import pairing
from timeslips_local_api.pairing import caller_is_private, clean_label, pair_message, request_pairing


@pytest.fixture(autouse=True)
def _reset():
    pairing.reset_for_tests()
    yield
    pairing.reset_for_tests()


def ask(answer):
    seen = []

    def _ask(message, seconds):
        seen.append((message, seconds))
        return answer

    return _ask, seen


def call(answer=True, **kw):
    a, seen = ask(answer)
    args = dict(token="tok", lan=True, client_host="192.168.1.20", computer="JANE-LAPTOP", user="Jane Smith", ask=a)
    args.update(kw)
    return request_pairing(**args), seen


def test_yes_returns_token_and_names_the_computer():
    token, seen = call(True)
    assert token == "tok"
    assert "Jane Smith on JANE-LAPTOP" in seen[0][0]
    assert seen[0][1] == 120


@pytest.mark.parametrize("answer,status", [(False, 403), (None, 408)])
def test_no_or_no_answer_gives_no_token(answer, status):
    with pytest.raises(ApiError) as err:
        call(answer)
    assert err.value.status_code == status


def test_refused_computer_waits_before_asking_again():
    clock = [1000.0]
    with pytest.raises(ApiError):
        call(False, now=lambda: clock[0])
    with pytest.raises(ApiError) as err:
        call(True, now=lambda: clock[0] + 10)
    assert err.value.status_code == 403
    token, _ = call(True, now=lambda: clock[0] + 301)
    assert token == "tok"


@pytest.mark.parametrize("host", ["8.8.8.8", None, "not-an-ip"])
def test_public_or_unknown_callers_never_see_a_box(host):
    with pytest.raises(ApiError) as err:
        call(True, client_host=host)
    assert err.value.status_code == 403


def test_sharing_off_never_shows_a_box():
    with pytest.raises(ApiError) as err:
        call(True, lan=False)
    assert err.value.status_code == 403


def test_only_one_box_at_a_time():
    assert pairing._prompt_lock.acquire(blocking=False)
    try:
        with pytest.raises(ApiError) as err:
            call(True)
        assert err.value.status_code == 409
    finally:
        pairing._prompt_lock.release()


def test_private_ranges():
    for host in ["10.0.0.5", "172.16.3.4", "192.168.0.9", "127.0.0.1", "169.254.1.1", "100.71.33.55"]:
        assert caller_is_private(host)
    assert not caller_is_private("100.200.0.1")


def test_labels_are_cleaned():
    assert clean_label("Jane <script>\n", "x") == "Jane script"
    assert clean_label("", "another computer") == "another computer"
    assert clean_label(None, "fallback") == "fallback"
    assert len(clean_label("a" * 500, "x")) == 64
    assert pair_message("PC1", "PC1").startswith("Allow PC1 to send")


def test_pair_route(monkeypatch):
    from fastapi.testclient import TestClient
    from timeslips_local_api import app as app_module

    class S:
        token = "tok"
        lan = True

    monkeypatch.setattr(app_module, "get_settings", lambda: S())
    monkeypatch.setattr(pairing, "ask_windows", lambda m, s: True)
    monkeypatch.setattr(app_module, "request_pairing", lambda **kw: request_pairing(ask=lambda m, s: True, **{**kw, "client_host": "192.168.1.9"}))
    res = TestClient(app_module.app).post("/pair", json={"computer": "JANE-LAPTOP", "user": "Jane"})
    assert res.status_code == 200
    assert res.json()["token"] == "tok"
    assert res.json()["hostName"]
