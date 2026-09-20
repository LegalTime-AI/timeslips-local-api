from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

from . import HELPER_VERSION
from .config import Settings, load_settings
from .errors import ApiError
from .firebird_store import FirebirdStore, RESERVED
from .health import health_payload
from .ledger import Ledger
from .models import SlipCreate, SlipPatch, VerifyRequest

app = FastAPI(title="timeslips-local-api", version=HELPER_VERSION)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def get_store() -> FirebirdStore:
    settings = get_settings()
    return FirebirdStore(settings, Ledger(settings.ledger_file()))


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse({"error": exc.message}, status_code=exc.status_code)


def require_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.token
    if not expected:
        raise ApiError(500, "TIMESLIPS_TOKEN is not set")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or supplied[len("Bearer ") :] != expected:
        raise ApiError(401, "unauthorized")


@app.get("/health")
def health() -> dict:
    return health_payload(get_settings())


@app.get("/v1/status")
def status(_: None = Depends(require_token), store: FirebirdStore = Depends(get_store)) -> dict:
    return store.status().model_dump()


@app.get("/v1/timekeepers")
def timekeepers(
    q: str | None = None,
    limit: int = 500,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return {"timekeepers": [n.model_dump() for n in store.list_names("timekeeper", q, limit)]}


@app.get("/v1/clients")
def clients(
    q: str | None = None,
    limit: int = 500,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return {"clients": [n.model_dump() for n in store.list_names("client", q, limit)]}


@app.get("/v1/activities")
def activities(
    q: str | None = None,
    limit: int = 500,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return {"activities": [n.model_dump() for n in store.list_names("activity", q, limit)]}


@app.get("/v1/slips")
def list_slips(
    date: str | None = None,
    clientNickname: str | None = Query(default=None),
    timekeeperNickname: str | None = Query(default=None),
    billed: bool | None = None,
    limit: int = 500,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    slips = store.list_slips(
        date=date,
        client_nickname=clientNickname,
        timekeeper_nickname=timekeeperNickname,
        billed=billed,
        limit=limit,
    )
    return {"slips": [s.model_dump() for s in slips]}


@app.get("/v1/slips/{slip_id}")
def get_slip(
    slip_id: str,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return store.get_slip(slip_id).model_dump()


@app.post("/v1/slips")
def create_slip(
    payload: SlipCreate,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    if idempotency_key and not payload.externalId:
        payload = payload.model_copy(update={"externalId": idempotency_key})
    return store.create_slip(payload).model_dump()


@app.patch("/v1/slips/{slip_id}")
def patch_slip(
    slip_id: str,
    payload: SlipPatch,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return store.update_slip(slip_id, payload).model_dump()


@app.delete("/v1/slips/{slip_id}")
def delete_slip(
    slip_id: str,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    store.delete_slip(slip_id)
    return {"ok": True}


@app.post("/v1/slips/verify")
def verify(
    payload: VerifyRequest,
    _: None = Depends(require_token),
    store: FirebirdStore = Depends(get_store),
) -> dict:
    return store.verify_slips(payload.ids).model_dump()


def _reserved(name: str):
    def handler(_: None = Depends(require_token)) -> dict:
        raise ApiError(501, f"{name} is not implemented in this version")

    return handler


for resource in RESERVED:
    app.add_api_route(f"/v1/{resource}", _reserved(resource), methods=["GET"])
    app.add_api_route(f"/v1/{resource}", _reserved(resource), methods=["POST"])
