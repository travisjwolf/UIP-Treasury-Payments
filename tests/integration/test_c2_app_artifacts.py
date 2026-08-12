import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
CONTROL_TOWER = ROOT / "src" / "apps" / "control-tower-web"
ACTION_APP = ROOT / "src" / "apps" / "wire-repair-approval"
ESCALATION_FIELDS = {
    "payment",
    "proposal",
    "gate",
    "reason",
    "evidence",
    "cutoff_time",
    "permitted_actions",
}


def test_control_tower_builds_all_fixture_cases_with_paginated_hero_detail():
    completed = subprocess.run(
        ["npm.cmd", "run", "build"],
        cwd=CONTROL_TOWER,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    cases = json.loads(
        (CONTROL_TOWER / "dist" / "cases.json").read_text(encoding="utf-8")
    )
    assert len(cases) == 40
    blocked = next(item for item in cases if item["case_id"] == "WIRE-8841")
    assert blocked["proposal"] == {
        "field": "beneficiary_account",
        "current_value": "882300441",
        "proposed_value": "8823004417",
    }
    assert blocked["outcome"] == "BLOCKED_POLICY"
    assert blocked["gate"] == "G1"
    assert blocked["confidence"] == 0.91
    assert blocked["evidence"]

    statement = r'''
import { paginate } from "./app/model.mjs";
const cases = Array.from({length: 40}, (_, index) => ({case_id: `${index}`}));
const first = paginate(cases, 1, 25);
const second = paginate(cases, 2, 25);
if (first.items.length !== 25 || second.items.length !== 15) process.exit(1);
if (first.totalPages !== 2 || second.page !== 2) process.exit(2);
'''
    model = subprocess.run(
        ["node", "--input-type=module", "-e", statement],
        cwd=CONTROL_TOWER,
        capture_output=True,
        text=True,
        check=False,
    )
    assert model.returncode == 0, model.stderr


def test_coded_action_app_schema_preserves_c1_escalation_contract_exactly():
    schema = json.loads(
        (ACTION_APP / "action-schema.json").read_text(encoding="utf-8")
    )

    assert set(schema) == {"inputs", "outputs", "inOuts", "outcomes"}
    assert set(schema["inputs"]["properties"]) == ESCALATION_FIELDS - {"proposal"}
    assert schema["outputs"]["properties"] == {}
    assert set(schema["inOuts"]["properties"]) == {"proposal"}
    assert (
        set(schema["inputs"]["properties"])
        | set(schema["inOuts"]["properties"])
    ) == ESCALATION_FIELDS
    assert list(schema["outcomes"]["properties"]) == [
        "Approve",
        "Edit",
        "Reject",
        "Escalate",
    ]
    assert not (ACTION_APP / "uipath.json").exists()


def test_coded_action_app_is_a_standalone_buildable_action_surface():
    completed = subprocess.run(
        ["npm.cmd", "run", "build"],
        cwd=ACTION_APP,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    package = json.loads((ACTION_APP / "package.json").read_text(encoding="utf-8"))
    project = json.loads(
        (ACTION_APP / "project.uiproj").read_text(encoding="utf-8")
    )
    source = (ACTION_APP / "src" / "components" / "ApprovalForm.tsx").read_text(
        encoding="utf-8"
    )

    assert package["name"] == "wire-repair-approval"
    assert "@uipath/coded-action-app" in package["dependencies"]
    assert "@uipath/uipath-typescript" not in package["dependencies"]
    assert project == {"Name": "wire-repair-approval", "ProjectType": "AppV2"}
    assert "completeTask(action, taskData)" in source
    assert "taskData.cutoff_time" in source
    assert "taskData.evidence" in source
    assert "taskData.permitted_actions" in source
