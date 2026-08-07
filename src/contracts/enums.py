from enum import Enum


class Outcome(str, Enum):
    RESOLVED = "RESOLVED"
    RESOLVED_LOW_CONFIDENCE = "RESOLVED_LOW_CONFIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    NEEDS_INFO = "NEEDS_INFO"
    EXHAUSTED = "EXHAUSTED"
    BLOCKED_POLICY = "BLOCKED_POLICY"


class EvidenceType(str, Enum):
    LOOKUP = "lookup"
    HISTORY_MATCH = "history_match"
    SANCTIONS = "sanctions"
    DOCUMENT = "document"
    CALL_TRANSCRIPT = "call_transcript"


class PolicyPath(str, Enum):
    AUTO_APPLY = "auto_apply"
    HUMAN_APPROVAL = "human_approval"
    COMPLIANCE_REFERRAL = "compliance_referral"
    CALLBACK_THEN_HUMAN = "callback_then_human"


class GateId(str, Enum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    G6 = "G6"
    G7 = "G7"
    G8 = "G8"
    G9 = "G9"
    G10 = "G10"


class SanctionsStatus(str, Enum):
    CLEAR = "clear"
    REVIEW = "review"
    MATCH = "match"
    UNKNOWN = "unknown"
