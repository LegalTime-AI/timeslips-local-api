# timeslips-local-api

Unofficial loopback HTTP API for **Sage Timeslips Premium** (Firebird).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

This is **not** a Sage product and **not** a supported Timeslips integration. Sage documents ODBC for reporting and warns that direct database writes can damage data. The working write path clones an unbilled `SLPTRANS` row over Firebird SQL. Use a **copy** database until you have confirmed a created slip on Timeslips Slip List.

LegalTime AI consumes this helper through a thin desktop adapter. The helper never imports LegalTime types.

## Safety

- Binds to `127.0.0.1` only.
- Default database is an exploration copy, not `...\Databases\Firm\MAIN.FDB`.
- Production firm files are **refused** unless `TIMESLIPS_ALLOW_PRODUCTION=1` (do not set this casually).
- Copy Slip List confirmation on this project’s test VM: 2026-09-20, `RECORDID` 104084 / `TRANSID` 104070. See [docs/GUI.md](docs/GUI.md).

## Install

Download **TimeslipsHelper.exe** from [Releases](https://github.com/LegalTime-AI/timeslips-local-api/releases/latest). Run it on the Windows computer that has Timeslips Premium. It is a windowed tray app: no terminal, one instance, auto-start at logon, and it keeps serving if Firebird is briefly down. Copy `pack/timeslips-helper.env.example` next to the exe as `timeslips-helper.env` and set `TIMESLIPS_FDB` to a **copy** of `MAIN.FDB`. The helper writes its token to `%LOCALAPPDATA%\TimeslipsHelper\timeslips-helper.env` so LegalTime can find it. Quit from the tray menu.

The helper still needs Timeslips Premium’s Firebird server (`FirebirdServerSageTimeslips`).

Developer install from source:

```powershell
git clone https://github.com/LegalTime-AI/timeslips-local-api.git
cd timeslips-local-api
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
$env:TIMESLIPS_TOKEN = "change-me"
$env:TIMESLIPS_FDB = "C:\path\to\MAIN_COPY.FDB"
$env:TIMESLIPS_PASSWORD = "<Sage-documented Premium SYSDBA password>"
python -m timeslips_local_api
```

Pack a Windows exe: `python -m pip install -e ".[pack]"` then `pyinstaller --noconfirm pack/timeslips-helper.spec`. The file is `dist/TimeslipsHelper.exe` (windowed, no console). Logs rotate under `%LOCALAPPDATA%\TimeslipsHelper\helper.log`. Copy token from the tray menu. `GET /health` is unauthenticated liveness plus a finite database reason; it never includes paths or Sage credentials.

Listens on `http://127.0.0.1:3051`.

- `GET /health` — unauthenticated
- All `/v1/*` — `Authorization: Bearer <token>`

Timeslips opens a **folder that contains `MAIN.FDB`**, not a bare `.fdb` path. See [docs/GUI.md](docs/GUI.md).

## v1

Timekeeping only. Bills, AR, trust, LEDES, expenses, and invoices are reserved (`501`).

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/status` | connection, write backend, capabilities |
| GET | `/v1/timekeepers` | timekeeper nicknames |
| GET | `/v1/clients` | client nicknames (Timeslips matters) |
| GET | `/v1/activities` | time activities only |
| GET | `/v1/slips` | filter by date / nicknames / billed |
| GET | `/v1/slips/{id}` | |
| POST | `/v1/slips` | create unbilled time slip (`Idempotency-Key` or `externalId`) |
| PATCH | `/v1/slips/{id}` | unbilled only |
| DELETE | `/v1/slips/{id}` | unbilled only |
| POST | `/v1/slips/verify` | `{ "ids": ["104080"] }` |

JSON uses ISO dates and duration in seconds. Callers never see Delphi dates, `NAMETYPE`, or `COUNTERS`.

Example create body:

```json
{
  "externalId": "legaltime-entry-uuid",
  "timekeeperNickname": "JDP",
  "clientNickname": "Labellarte Trusts",
  "activityNickname": "CLE",
  "date": "2026-09-18",
  "durationSeconds": 720,
  "billable": true,
  "description": "Reviewed CLE materials on trust administration."
}
```

Write backend: `TIMESLIPS_WRITE_BACKEND=sql` (working) · `dll` (unused; see [docs/dll-probe.md](docs/dll-probe.md)) · `tsimport` (GUI importer, not unattended).

## LegalTime

See [docs/LEGALTIME.md](docs/LEGALTIME.md). The desktop adapter lives in [LegalTime-AI/legaltime-ai](https://github.com/LegalTime-AI/legaltime-ai).

## Tests

```powershell
$env:TIMESLIPS_TOKEN = "test-token"
$env:TIMESLIPS_FDB = "C:\path\to\MAIN_COPY.FDB"
python -m pytest -q
```

Tests write only the configured copy database.

## License

MIT. Sage, Timeslips, and related marks belong to their owners.
