# TSDBAP32 probe

Sage Timeslips ships a closed partner API as `TSDBAP32.DLL` (BDE-style table access) plus `TSDB0132.DLL` (0 exports on this install) and `TSDlgApi.dll` (GUI dialogs). iSlips/Amicus historically used the partner API. There is no public header, `.lib`, or CreateSlip prototype in `C:\Program Files (x86)\Timeslips`.

This project’s `TIMESLIPS_WRITE_BACKEND=dll` flag exists so a future implementation can slot in without changing HTTP. The 2026-09-20 dump on Timeslips 30.0.9.196 found **no named create-slip export**, so the flag stays unused and returns HTTP 501.

Working writes use `TIMESLIPS_WRITE_BACKEND=sql` (clone a native unbilled `SLPTRANS` row and bump `COUNTERS`). That path is unofficial.

## How to dump

```powershell
python scripts\dump_dll_exports.py
python scripts\dump_dll_exports.py "C:\Program Files (x86)\Timeslips\TSDlgApi.dll"
```

Checked-in snapshot: [tsdbap32-exports.txt](tsdbap32-exports.txt) (209 names).

## Findings (this VM)

| Module | Result |
|---|---|
| `TSDBAP32.DLL` | 209 exports. Generic record I/O: `DB_APIInitialize`, `DB_NewRecord`, `DB_SaveRecord`, `DB_DeleteRecord`, `DB_GetField`, `DB_GotoRecordID`. |
| `TSDB0132.DLL` | 0 named exports (forwarder / resource module). |
| `TSDlgApi.dll` | 7 exports, including **`TSDLG_SlipEntry`** — a Slip Entry **dialog**, not a silent insert. |

Slip-adjacent `TSDBAP32` names (none are `CreateSlip` / `InsertSlip` / `NewSlip`):

- `DB_TSApplySlipDefaults`, `DB_TSApplySlipDefaultsByTable`
- `DB_TSNewTransKey` (key helper, not an insert)
- `DB_TSSlipAlreadyExists`, `DB_TSSlipIsDefault`, `DB_TSSlipClearDefault`
- `DB_TSSlipRateTableLookup`, `DB_TSSlipRateLevelByRateInfo`
- `DB_TSExtendTransTable`, `DB_TSTransIndexAndRange`

`DB_NewRecord` + `DB_SaveRecord` could theoretically write `SLPTRANS` if calling convention, table IDs, and field buffers were known. They are not documented here. Loading the DLL and guessing `stdcall` arguments would risk crashing Timeslips. This helper does not call them.

`TSDLG_SlipEntry` would require an interactive desktop session and must not be used as an unattended write backend.

## Flag

`TIMESLIPS_WRITE_BACKEND=dll` → `DllSlipWriter` → HTTP 501 (`write-backend dll is not implemented in this version`).

Leave that stub in place. Do not wire ctypes until Sage or a partner kit documents a silent create-slip entry point and it is proven on `MAIN_COPY.FDB`.
