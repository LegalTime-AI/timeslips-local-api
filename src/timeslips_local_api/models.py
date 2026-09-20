from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NameKind = Literal["timekeeper", "client", "activity"]


class NameRecord(BaseModel):
    id: str
    nickname: str
    nickname2: str = ""
    fullName: str = ""
    kind: NameKind
    status: str = "open"
    email: str | None = None


class Slip(BaseModel):
    id: str
    transId: str
    timekeeperNickname: str
    clientNickname: str
    activityNickname: str
    date: str
    durationSeconds: int
    hours: float
    rate: float
    amount: float
    billable: bool
    billed: bool
    description: str
    externalId: str | None = None


class SlipCreate(BaseModel):
    externalId: str | None = None
    timekeeperNickname: str
    clientNickname: str
    activityNickname: str
    date: str
    durationSeconds: int = Field(gt=0)
    billable: bool = True
    description: str = ""


class SlipPatch(BaseModel):
    timekeeperNickname: str | None = None
    clientNickname: str | None = None
    activityNickname: str | None = None
    date: str | None = None
    durationSeconds: int | None = Field(default=None, gt=0)
    billable: bool | None = None
    description: str | None = None


class VerifyRequest(BaseModel):
    ids: list[str]


class VerifyResult(BaseModel):
    stillExists: list[str]
    missing: list[str]
    billed: list[str]


class Status(BaseModel):
    connected: bool
    database: str
    writeBackend: str
    capabilities: list[str]
    productionWritesBlocked: bool
    timeslipsVersion: str | None = None
