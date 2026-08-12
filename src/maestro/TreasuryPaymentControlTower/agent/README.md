# Wire Repair Agent

This project is the Bravo-owned, read-only UiPath coded agent for treasury wire
repair. Run UiPath lifecycle commands from this directory so `langgraph.json`
and the deploy-local `wire_repair_agent` package resolve correctly.

After changing a public Pydantic input or output model, regenerate the UiPath
metadata and then restore JSON Schema nullability with the checked-in sync step:

```powershell
uip codedagent init --no-agents-md-override
python scripts/sync_entrypoints.py
```

The sync is required for the current CLI because its entry-point generator
flattens nullable Pydantic fields. Repository tests validate the checked-in
schema against both hero fixtures and a valid `EXHAUSTED` output.
