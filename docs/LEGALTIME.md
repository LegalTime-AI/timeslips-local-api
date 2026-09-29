# LegalTime mapping

This helper is Timeslips-shaped. LegalTime’s desktop adapter is a thin HTTP client of `/v1` and does not import this package.

| LegalTime `PracticeManagementIntegration` | Helper |
|---|---|
| helper liveness | unauthenticated `GET /health` (`ok`, `apiVersion`, `hostName`, finite `database.reason`). Online when this returns; offline when it does not. |
| `getStatus()` | portal occupancy plus `/health` and `GET /v1/status` |
| `listMatters()` / `listClients()` | `GET /v1/clients` (client nickname is the matter) |
| `listBillingCodes()` | `GET /v1/activities` |
| timekeeper | `GET /v1/timekeepers` (match `email` to the LegalTime account) |
| `pushEntry()` | `POST /v1/slips` with `externalId` = LegalTime entry id |
| `updateEntry()` | `PATCH /v1/slips/{id}` |
| `deleteEntry()` / Undo Release | `DELETE /v1/slips/{id}` |
| `verifyEntries()` | `POST /v1/slips/verify` |
| `external_id` | slip `id` (Timeslips `RECORDID` as string) |

Same-computer use stays on `http://127.0.0.1:3051` and reads the token from `%LOCALAPPDATA%\TimeslipsHelper\timeslips-helper.env`. With `TIMESLIPS_LAN=1`, the helper also beacons on UDP `3052`:

```json
{"service":"timeslips-local-api","port":3051,"hostName":"TIMESLIPS-PC","helperVersion":"0.3.0"}
```

LegalTime on another laptop may call that host only when the address is loopback, private (RFC1918), link-local, or Tailscale (`100.64.0.0/10`). The token is pasted once in LegalTime. It is not in the beacon. Portal occupancy still means Timeslips is the connected billing system when the helper is offline.

When Timeslips is occupied on the portal and the helper is down or Firebird is unreachable, LegalTime reports a privacy-safe operational issue to Sentry (`helper:not_running`, `helper:unresponsive`, `helper:database_unreachable`, `helper:token_missing`, `helper:token_mismatch`) with a finite `diagnostic_code`. Paths and Sage credentials never leave the helper.

Reserved capabilities (`expenses`, `references`, `invoices`) return 501 so the adapter can feature-detect from `GET /v1/status`.
