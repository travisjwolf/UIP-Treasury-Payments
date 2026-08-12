from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .tooling import EvidenceRecord, PaymentCaseLike, ToolResult


class CallbackTranscriptError(ValueError):
    """Raised when callback evidence cannot be safely reconciled."""


_REQUIRED_FIELDS = {
    "format_version",
    "case_id",
    "recorded_at",
    "customer_name",
    "beneficiary_name",
    "remittance_reference",
    "beneficiary_account_last_four",
    "full_replacement_account_provided",
    "full_replacement_account_authorized",
    "transcript_text",
}
_TRANSCRIPT_FREE_TEXT_FIELDS = (
    "customer_name",
    "beneficiary_name",
    "remittance_reference",
    "transcript_text",
)
_FULL_ACCOUNT_PATTERN = re.compile(r"(?<!\d)\d(?:[ \-/.]*\d){4,}(?!\d)")


def parse_callback_transcript(transcript: str) -> dict[str, Any]:
    """Parse the explicit callback fixture format and reject unsafe content."""
    fields: dict[str, str] = {}
    for line_number, raw_line in enumerate(transcript.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if ": " not in line:
            raise CallbackTranscriptError(
                f"malformed callback transcript line {line_number}"
            )
        key, value = line.split(": ", 1)
        if key not in _REQUIRED_FIELDS:
            raise CallbackTranscriptError(
                f"unknown callback transcript field: {key}"
            )
        if key in fields:
            raise CallbackTranscriptError(
                f"duplicate callback transcript field: {key}"
            )
        fields[key] = value.strip()

    missing = sorted(_REQUIRED_FIELDS - fields.keys())
    if missing:
        raise CallbackTranscriptError(
            "missing callback transcript fields: " + ", ".join(missing)
        )
    if any(not fields[key] for key in _REQUIRED_FIELDS):
        raise CallbackTranscriptError("callback transcript fields must not be blank")
    if fields["format_version"] != "CALLBACK_TRANSCRIPT_V1":
        raise CallbackTranscriptError("unsupported callback transcript format")
    if re.fullmatch(r"WIRE-\d{4}", fields["case_id"]) is None:
        raise CallbackTranscriptError("invalid callback case identity")
    try:
        recorded_at = datetime.fromisoformat(
            fields["recorded_at"].replace("Z", "+00:00")
        )
    except ValueError as error:
        raise CallbackTranscriptError("invalid callback recorded timestamp") from error
    if recorded_at.tzinfo is None:
        raise CallbackTranscriptError("callback recorded timestamp must include timezone")
    if any(
        _FULL_ACCOUNT_PATTERN.search(fields[key])
        for key in _TRANSCRIPT_FREE_TEXT_FIELDS
    ):
        raise CallbackTranscriptError(
            "callback transcript contains a full account in a free-text field"
        )
    if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", fields["remittance_reference"]) is None:
        raise CallbackTranscriptError("invalid callback remittance reference")
    if re.fullmatch(r"\d{4}", fields["beneficiary_account_last_four"]) is None:
        raise CallbackTranscriptError(
            "callback beneficiary account confirmation must be last four only"
        )

    boolean_fields: dict[str, bool] = {}
    for key in (
        "full_replacement_account_provided",
        "full_replacement_account_authorized",
    ):
        if fields[key] not in {"true", "false"}:
            raise CallbackTranscriptError(f"invalid callback boolean field: {key}")
        boolean_fields[key] = fields[key] == "true"
    if any(boolean_fields.values()):
        raise CallbackTranscriptError(
            "callback transcript must not provide or authorize a full account"
        )
    return {
        "case_id": fields["case_id"],
        "recorded_at": fields["recorded_at"],
        "customer_name": fields["customer_name"],
        "beneficiary_name": fields["beneficiary_name"],
        "remittance_reference": fields["remittance_reference"],
        "beneficiary_account_last_four": fields[
            "beneficiary_account_last_four"
        ],
        **boolean_fields,
        "transcript_text": fields["transcript_text"],
    }


class CallbackTranscriptAnalyzer:
    """Load and reconcile only explicitly mapped prerecorded transcripts."""

    _DATA_DIRECTORY = Path(__file__).resolve().parent / "data"
    _ASSETS: Mapping[str, tuple[Path, str]] = {
        "WIRE-8877": (
            _DATA_DIRECTORY / "WIRE-8877-callback-transcript.txt",
            "fixture://callback-transcripts/WIRE-8877.txt",
        )
    }

    @staticmethod
    def _normalized_name(value: str) -> str:
        with_and = value.casefold().replace("&", " and ")
        return " ".join(re.sub(r"[^a-z0-9]+", " ", with_and).split())

    @classmethod
    def is_mapped_case(cls, case_id: str) -> bool:
        return case_id in cls._ASSETS

    def analyze(self, case: PaymentCaseLike) -> ToolResult:
        asset = self._ASSETS.get(case.case_id)
        if asset is None:
            raise CallbackTranscriptError(
                f"callback transcript is not mapped for case {case.case_id}"
            )
        asset_path, source = asset
        try:
            parsed = parse_callback_transcript(
                asset_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError) as error:
            raise CallbackTranscriptError(
                f"mapped callback transcript is unavailable for case {case.case_id}"
            ) from error
        if parsed["case_id"] != case.case_id:
            raise CallbackTranscriptError(
                "callback transcript identity does not match the payment case"
            )

        customer_status = (
            "match"
            if self._normalized_name(parsed["customer_name"])
            == self._normalized_name(case.customer_name)
            else "conflict"
        )
        beneficiary_status = (
            "match"
            if self._normalized_name(parsed["beneficiary_name"])
            == self._normalized_name(case.beneficiary_name)
            else "conflict"
        )
        reference_status = (
            "match"
            if parsed["remittance_reference"].casefold()
            in case.remittance_info.casefold()
            else "conflict"
        )
        if len(case.beneficiary_account) < 4:
            raise CallbackTranscriptError(
                "payment account cannot be reconciled against a last four"
            )
        payment_last_four = case.beneficiary_account[-4:]
        account_status = (
            "match"
            if parsed["beneficiary_account_last_four"] == payment_last_four
            else "conflict"
        )

        reconciliation = {
            "customer_name": {
                "payment_value": case.customer_name,
                "transcript_value": parsed["customer_name"],
                "status": customer_status,
            },
            "beneficiary_name": {
                "payment_value": case.beneficiary_name,
                "transcript_value": parsed["beneficiary_name"],
                "status": beneficiary_status,
            },
            "remittance_reference": {
                "payment_value": case.remittance_info,
                "transcript_value": parsed["remittance_reference"],
                "status": reference_status,
            },
            "beneficiary_account": {
                "payment_last_four": payment_last_four,
                "transcript_last_four": parsed[
                    "beneficiary_account_last_four"
                ],
                "status": account_status,
            },
        }
        flagged_fields = [
            field
            for field, result in reconciliation.items()
            if result["status"] != "match"
        ]
        data = {
            "transcript": {
                "case_id": parsed["case_id"],
                "recorded_at": parsed["recorded_at"],
                "text": parsed["transcript_text"],
            },
            "extracted_entities": {
                "customer_name": parsed["customer_name"],
                "beneficiary_name": parsed["beneficiary_name"],
                "remittance_reference": parsed["remittance_reference"],
                "beneficiary_account_last_four": parsed[
                    "beneficiary_account_last_four"
                ],
                "full_replacement_account_provided": parsed[
                    "full_replacement_account_provided"
                ],
                "full_replacement_account_authorized": parsed[
                    "full_replacement_account_authorized"
                ],
            },
            "reconciliation": reconciliation,
            "flagged_fields": flagged_fields,
        }
        return ToolResult(
            tool_name="callback_transcript",
            data=data,
            evidence=EvidenceRecord(
                case_id=case.case_id,
                type="call_transcript",
                source=source,
                content=json.dumps(data, sort_keys=True),
                produced_by="callback_transcript",
                timestamp=parsed["recorded_at"],
            ),
        )
