# LegalTime mapping

This helper is Timeslips-shaped. LegalTime’s desktop adapter is a thin HTTP client of `/v1` and does not import this package.

| LegalTime `PracticeManagementIntegration` | Helper |
|---|---|
| helper liveness | unauthenticated `GET /health` (`ok`, `apiVersion`, finite `database.reason`) |
| `getStatus()` | portal occupancy plus `/health` and `GET /v1/status` |
| `listMatters()` / `listClients()` | `GET /v1/clients` (client nickname is the matter) |
| `listBillingCodes()` | `GET /v1/activities` |
| timekeeper | `GET /v1/timekeepers` (match `email` to the LegalTime account) |
| `pushEntry()` | `POST /v1/slips` with `externalId` = LegalTime entry id |
| `updateEntry()` | `PATCH /v1/slips/{id}` |
| `deleteEntry()` / Undo Release | `DELETE /v1/slips/{id}` |
| `verifyEntries()` | `POST /v1/slips/verify` |
| `external_id` | slip `id` (Timeslips `RECORDID` as string) |

When Timeslips is occupied on the portal and the helper is down or Firebird is unreachable, LegalTime reports a privacy-safe operational issue to Sentry (`helper:not_running`, `helper:unresponsive`, `helper:database_unreachable`, `helper:token_missing`, `helper:token_mismatch`) with a finite `diagnostic_code`. Paths and Sage credentials never leave the helper.

Reserved capabilities (`expenses`, `references`, `invoices`) return 501 so the adapter can feature-detect from `GET /v1/status`.
