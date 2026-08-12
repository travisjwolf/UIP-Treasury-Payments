from __future__ import annotations

import json
from io import StringIO
from typing import Never

from src.platform.cli import main


class ExplodingRunner:
    def run(self, argv: object) -> Never:
        raise AssertionError(f"offline or unapproved command unexpectedly executed: {argv!r}")


def test_offline_clean_cli_emits_a_machine_readable_plan_without_uip_calls() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["plan", "--offline-clean"],
        runner=ExplodingRunner(),
        stdout=stdout,
        stderr=stderr,
    )

    output = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert output["mode"] == "offline-clean"
    assert output["create_count"] == len(output["actions"])
    assert output["requires_schema_approval"] is True
    assert stderr.getvalue() == ""


def test_apply_cli_refuses_to_run_without_both_explicit_approvals() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "apply",
            "--base-url",
            "https://staging.uipath.com",
            "--organization",
            "approved-org",
            "--tenant",
            "approved-tenant",
        ],
        runner=ExplodingRunner(),
        stdout=stdout,
        stderr=stderr,
    )

    output = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert output["error"] == "ApprovalRequiredError"
    assert "--confirm" in output["message"]
    assert stdout.getvalue() == ""


def test_online_plan_requires_an_explicit_expected_base_url_organization_and_tenant() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["plan"],
        runner=ExplodingRunner(),
        stdout=stdout,
        stderr=stderr,
    )

    output = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert output["error"] == "UsageError"
    assert "--base-url" in output["message"]
    assert "--organization" in output["message"]
    assert "--tenant" in output["message"]
