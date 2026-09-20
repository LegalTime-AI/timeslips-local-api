# GUI check (copy database only)

Timeslips treats a firm as a **folder that contains `MAIN.FDB`**, not as the `.fdb` path itself. Opening `DB:C:\TimeslipsExplore\MAIN_COPY.FDB` fails (it looks for `MAIN_COPY.FDB\MAIN.FDB`). Use a folder:

```
C:\TimeslipsExplore\CopyFirm\MAIN.FDB
```

On this VM that file is an NTFS hard link to `C:\TimeslipsExplore\MAIN_COPY.FDB` (same bytes the API writes).

## Open the copy

1. Close Sage Timeslips if it is using production `C:\ProgramData\Sage\Timeslips\Databases\Firm\`.
2. Backup `HKCU\Software\Sage\Timeslips` (Timeslips remembers `DatabasePath` and will otherwise reopen the copy next time).
3. Start:

```powershell
& "C:\Program Files (x86)\Timeslips\Timeslip.exe" "DB:C:\TimeslipsExplore\CopyFirm"
```

4. **Slips → Time and Expense Slips** (`Ctrl+M`). Newest slips are at the bottom when View By is ID.
5. Confirm the API slip, then **File → Exit**.
6. Restore the registry backup so the next launch is production `...\Databases\Firm\` again.

Until you set `TIMESLIPS_ALLOW_PRODUCTION=1`, the API refuses writes to `...\Databases\Firm\MAIN.FDB`.

## Result (2026-09-20)

Opened **CopyFirm** only (status bar `C:\TimeslipsExplore\CopyFirm\`). Production `MAIN.FDB` was not the attached database.

`POST /v1/slips` created unbilled time slip:

| Field | Value |
|---|---|
| `id` (RECORDID) | `104084` |
| `transId` | `104070` |
| Timekeeper | JDP |
| Client | Labellarte Trusts |
| Activity | CLE |
| Date | 2026-09-20 |
| Time | 0:12:00 (720 seconds) |
| Rate / amount | $595 / $119.00 |
| Status | Billable, unbilled |
| Description (Firebird) | `timeslips-local-api GUI check 2026-09-20 unbilled time slip` |

Time and Expense Slip List showed that row as the newest slip (ID column displays **TRANSID** `104070`). The 2026-09-18 exploration proof (`TRANSID` 104066 / `RECORDID` 104080) is on the same list.

Slip Entry / pre-bill were not completed in that session: opening Slip Entry raised Timeslips’ own “Failed to read from streamed data” dialog against an unrelated 2012 slip as well, so it is a UI stream error, not proof that the SQL row is invalid. The list view is the confirmation.

Production writes stay blocked by default.
