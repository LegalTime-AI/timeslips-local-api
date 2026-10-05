# timeslips-local-api

Unofficial local HTTP API for **Sage Timeslips Premium** (Firebird).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

This is **not** a Sage product and **not** a supported Timeslips integration. Sage documents ODBC for reporting and warns that direct database writes can damage data. The working write path clones an unbilled `SLPTRANS` row over Firebird SQL. Use a **copy** database until you have confirmed a created slip on Timeslips Slip List.

LegalTime AI consumes this helper through a thin desktop adapter. The helper never imports LegalTime types.

## Safety

- Binds to `127.0.0.1` unless `TIMESLIPS_LAN=1`, which listens on the private network so LegalTime on another laptop can call it. Do not port-forward that port to the internet.
- Default database is an exploration copy, not `...\Databases\Firm\MAIN.FDB`.
- Production firm files are **refused** unless `TIMESLIPS_ALLOW_PRODUCTION=1` (do not set this casually).
- Copy Slip List confirmation on this project’s test VM: 2026-09-20, `RECORDID` 104084 / `TRANSID` 104070. See [docs/GUI.md](docs/GUI.md).

## Install

Download **TimeslipsHelper.exe** from [Releases](https://github.com/LegalTime-AI/timeslips-local-api/releases/latest) and run it on the Windows computer that has Timeslips Premium. There is no installer and no env file to edit. The helper looks up the database Timeslips has open, then the usual firm file, then a copy. If it cannot find one, it asks you to choose `MAIN.FDB`. A live `Databases\Firm\MAIN.FDB` asks once before LegalTime can create slips there. The first launch also turns on sharing for other computers on this private network, starts the helper at logon, and adds a Windows Firewall rule for Private networks (one approval prompt). It writes a token to `%LOCALAPPDATA%\TimeslipsHelper\timeslips-helper.env`.

On each other laptop, open LegalTime Settings and paste that token once. The helper menu item is **Copy token**. Both computers must be on the same private network (office LAN or a VPN such as Tailscale). Do not port-forward the helper to the internet. Uncheck **Share with other computers** to keep the helper on this PC only; that takes effect the next time the helper opens.

The helper still needs Timeslips Premium’s Firebird server (`FirebirdServerSageTimeslips`). A UDP beacon on port `3052` announces the computer name and port only — never the token. `GET /health` stays unauthenticated so LegalTime can show the Timeslips computer as online or offline. All `/v1` reads and writes still require the bearer token.

A packed helper checks GitHub releases on startup and about every six hours. If the database is unreachable, it checks right away and again about every 15 minutes. A newer `TimeslipsHelper.exe` replaces this one only after `SHA256SUMS` matches. That updates the helper program. It does not change the Timeslips database. Set `TIMESLIPS_NO_UPDATE=1` to skip updates. Dev runs do not update.

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

Listens on `http://127.0.0.1:3051`, or on every interface at that port when `TIMESLIPS_LAN=1`.

- `GET /health` — unauthenticated
- All `/v1/*` — `Authorization: Bearer <token>`

Timeslips opens a **folder that contains `MAIN.FDB`**, not a bare `.fdb` path. See [docs/GUI.md](docs/GUI.md).

## v1

Timekeeping only. Bills, AR, trust, LEDES, expenses, and invoices are reserved (`501`).

| Method | Path | Notes |
|---|---|---|
| GET | `/v1/status` | connection, write backend, capabilities |
| GET | `/v1/timekeepers` | timekeeper nicknames (`limit` default 500, cap 500) |
| GET | `/v1/clients` | open client nicknames (Timeslips matters; inactive excluded; `limit` default 500) |
| GET | `/v1/activities` | open time activities (inactive excluded; `limit` default 500) |
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
