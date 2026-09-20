# LegalTime mapping

This helper is Timeslips-shaped. LegalTime’s desktop adapter is a thin HTTP client of `/v1` and does not import this package.

| LegalTime `PracticeManagementIntegration` | Helper |
|---|---|
| `getStatus()` | `GET /v1/status` |
| `listMatters()` / `listClients()` | `GET /v1/clients` (client nickname is the matter) |
| `listBillingCodes()` | `GET /v1/activities` |
| timekeeper | `GET /v1/timekeepers` (match `email` to the LegalTime account) |
| `pushEntry()` | `POST /v1/slips` with `externalId` = LegalTime entry id |
| `updateEntry()` | `PATCH /v1/slips/{id}` |
| `deleteEntry()` / Undo Release | `DELETE /v1/slips/{id}` |
| `verifyEntries()` | `POST /v1/slips/verify` |
| `external_id` | slip `id` (Timeslips `RECORDID` as string) |

Reserved capabilities (`expenses`, `references`, `invoices`) return 501 so the adapter can feature-detect from `GET /v1/status`.
