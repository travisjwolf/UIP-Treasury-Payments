"""Command-line entry point for safe platform planning and approved apply."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .manifest import DEFAULT_MANIFEST_PATH, ManifestValidationError, load_manifest
from .provisioner import (
    CommandRunner,
    Provisioner,
    ProvisioningError,
    SubprocessCommandRunner,
    TenantTarget,
    redact_sensitive_text,
)


class UsageError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.platform",
        description="Plan or additively provision Payment Control Tower platform state.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to the declarative platform manifest.",
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    plan = subparsers.add_parser("plan", help="Plan without mutation.")
    plan.add_argument(
        "--offline-clean",
        action="store_true",
        help="Assume an empty tenant and perform no uip calls.",
    )
    plan.add_argument("--base-url", help="Expected active UiPath BaseUrl.")
    plan.add_argument("--organization", help="Expected active UiPath organization name.")
    plan.add_argument("--tenant", help="Expected active UiPath tenant name.")

    apply_parser = subparsers.add_parser(
        "apply", help="Apply only missing resources, then verify zero creates remain."
    )
    apply_parser.add_argument(
        "--base-url", required=True, help="Expected active UiPath BaseUrl."
    )
    apply_parser.add_argument(
        "--organization", required=True, help="Expected active UiPath organization name."
    )
    apply_parser.add_argument(
        "--tenant", required=True, help="Expected active UiPath tenant name."
    )
    apply_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the reviewed plan may create missing resources.",
    )
    apply_parser.add_argument(
        "--approve-schema-mappings",
        action="store_true",
        help="Approve declared logical-to-physical reserved-name mappings.",
    )
    return parser


def _write_json(stream: TextIO, value: object) -> None:
    stream.write(json.dumps(value, indent=2, sort_keys=True))
    stream.write("\n")


def _target(
    base_url: str | None,
    organization: str | None,
    tenant: str | None,
) -> TenantTarget:
    missing = [
        option
        for option, value in (
            ("--base-url", base_url),
            ("--organization", organization),
            ("--tenant", tenant),
        )
        if not value
    ]
    if missing:
        raise UsageError(f"online plan requires {' and '.join(missing)}")
    try:
        return TenantTarget(
            base_url=base_url or "",
            organization=organization or "",
            tenant=tenant or "",
        )
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    try:
        args = _parser().parse_args(list(argv) if argv is not None else None)
        manifest = load_manifest(args.manifest)
        provisioner = Provisioner(manifest, runner or SubprocessCommandRunner())

        if args.operation == "plan":
            if args.offline_clean:
                if args.base_url or args.organization or args.tenant:
                    raise UsageError(
                        "--offline-clean cannot be combined with --base-url, "
                        "--organization, or --tenant"
                    )
                plan = provisioner.plan_assuming_clean()
            else:
                plan = provisioner.plan(
                    _target(args.base_url, args.organization, args.tenant)
                )
            _write_json(output, plan.to_dict())
            return 0

        target = _target(args.base_url, args.organization, args.tenant)
        report = provisioner.apply(
            target,
            confirm=args.confirm,
            approve_schema_mappings=args.approve_schema_mappings,
        )
        _write_json(
            output,
            {
                "result": "success",
                "target": target.display_name,
                "created_count": report.created_count,
                "verification_create_count": report.verification_plan.create_count,
            },
        )
        return 0
    except (ManifestValidationError, ProvisioningError, UsageError) as exc:
        _write_json(
            errors,
            {
                "error": type(exc).__name__,
                "message": redact_sensitive_text(str(exc)),
            },
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
