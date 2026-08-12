# Control Tower demo app

This is a tenant-neutral, fixture-driven Coded Web App prototype. `npm run build`
reads all 40 canonical files in `fixtures/cases/` and writes a static bundle to
the ignored `dist/` directory. The WIRE-8802, WIRE-8841, and WIRE-8877 records
include the verified runtime results needed for the end-to-end demo; remaining
records show their canonical expected path while awaiting runtime execution.

The app deliberately makes no UiPath SDK or live-tenant calls. The existing
`uipath.json` tenant and OAuth fields remain blank until the nominated staging
tenant and OAuth client ID are supplied. No credentials or guessed identifiers
are checked in.

```powershell
npm install
npm run build
npm run verify:model
```

The queue uses 25-row pages. Selecting WIRE-8841 opens the exact evidence-backed
account repair (`882300441` to `8823004417`); the action notice reports whether
the operator completed the demo decision inside the 20-second target and makes
the sandbox/no-write boundary explicit.
