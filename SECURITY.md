# Security

`timeslips-local-api` is an unofficial local helper. Treat it as a privileged process on the Timeslips workstation.

- Bind only to loopback. The process refuses non-loopback `TIMESLIPS_BIND`.
- Require `TIMESLIPS_TOKEN` for every `/v1` route. `GET /health` is the only open endpoint.
- Point `TIMESLIPS_FDB` at a **copy** until Slip List confirms writes. Production `...\Databases\Firm\MAIN.FDB` is blocked unless `TIMESLIPS_ALLOW_PRODUCTION=1`.
- Do not log or return SYSDBA, Firebird SQL, or production paths in API error bodies.
- SQL writes clone native unbilled slips. They are unsupported by Sage and can damage a firm file.

Report security issues privately to the LegalTime AI maintainers rather than filing a public GitHub issue that includes a firm database path or credentials.
