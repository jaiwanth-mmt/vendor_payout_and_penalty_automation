from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal


CaseReviewStatus = Literal["auto_ready", "needs_review", "missing_evidence", "contradiction", "failed"]
EvidenceStatus = Literal["available", "missing", "error"]
AgentStepStatus = Literal["completed", "warning", "failed"]
DecisionSource = Literal["llm", "fallback"]

AGENT_OUTPUT_COLUMNS = [
    "agent_review_status",
    "agent_decision",
    "agent_decision_source",
    "agent_confidence",
    "agent_recommended_action",
    "agent_review_reason",
    "agent_rationale",
    "agent_evidence_ids",
    "agent_llm_error",
]


def json_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, pd_na_types()):
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value


def pd_na_types() -> tuple[type[Any], ...]:
    try:
        import pandas as pd

        return (type(pd.NA), type(pd.NaT))
    except Exception:
        return ()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def clean_number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        import pandas as pd

        if pd.isna(value):
            return 0.0
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class EvidenceItem:
    id: str
    title: str
    source: str
    status: EvidenceStatus
    summary: str
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "status": self.status,
            "summary": self.summary,
            "fields": json_safe(self.fields),
            "error": self.error,
        }


@dataclass
class AgentTraceStep:
    agent: str
    action: str
    status: AgentStepStatus
    summary: str
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "action": self.action,
            "status": self.status,
            "summary": self.summary,
            "evidence_ids": self.evidence_ids,
            "metadata": json_safe(self.metadata),
        }


@dataclass
class AgentDecision:
    agent: str
    decision: str
    complaint_categories: list[str]
    confidence: float
    recommended_recovery_amount: float
    rationale: str
    recommended_action: str
    review_status: CaseReviewStatus
    review_reason: str
    evidence_ids: list[str] = field(default_factory=list)
    decision_source: DecisionSource = "fallback"
    llm_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "decision": self.decision,
            "decision_source": self.decision_source,
            "complaint_categories": self.complaint_categories,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 2),
            "recommended_recovery_amount": round(self.recommended_recovery_amount, 2),
            "rationale": self.rationale,
            "recommended_action": self.recommended_action,
            "review_status": self.review_status,
            "review_reason": self.review_reason,
            "evidence_ids": self.evidence_ids,
            "llm_error": self.llm_error,
        }


@dataclass
class ClaimCase:
    booking_id: str
    sub_category: str
    remarks: str
    recoverable_amount: float
    row_index: int
    evidence: list[EvidenceItem] = field(default_factory=list)
    trace: list[AgentTraceStep] = field(default_factory=list)
    specialist_decision: AgentDecision | None = None
    judge_decision: AgentDecision | None = None

    @property
    def final_decision(self) -> AgentDecision | None:
        return self.judge_decision or self.specialist_decision

    @property
    def review_status(self) -> CaseReviewStatus:
        decision = self.final_decision
        return decision.review_status if decision else "failed"

    def evidence_by_id(self) -> dict[str, EvidenceItem]:
        return {item.id: item for item in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        decision = self.final_decision
        return {
            "booking_id": self.booking_id,
            "sub_category": self.sub_category,
            "remarks": self.remarks,
            "recoverable_amount": round(self.recoverable_amount, 2),
            "row_index": self.row_index,
            "review_status": self.review_status,
            "evidence": [item.to_dict() for item in self.evidence],
            "trace": [step.to_dict() for step in self.trace],
            "specialist_decision": self.specialist_decision.to_dict() if self.specialist_decision else None,
            "judge_decision": self.judge_decision.to_dict() if self.judge_decision else None,
            "final_decision": decision.to_dict() if decision else None,
        }

    def to_agent_columns(self) -> dict[str, Any]:
        decision = self.final_decision
        if decision is None:
            return {
                "agent_review_status": "failed",
                "agent_decision": "failed",
                "agent_decision_source": "fallback",
                "agent_confidence": 0,
                "agent_recommended_action": "Review manually",
                "agent_review_reason": "No agent decision was produced.",
                "agent_rationale": "",
                "agent_evidence_ids": "",
                "agent_llm_error": "",
            }

        return {
            "agent_review_status": decision.review_status,
            "agent_decision": decision.decision,
            "agent_decision_source": decision.decision_source,
            "agent_confidence": round(decision.confidence, 2),
            "agent_recommended_action": decision.recommended_action,
            "agent_review_reason": decision.review_reason,
            "agent_rationale": decision.rationale,
            "agent_evidence_ids": ", ".join(decision.evidence_ids),
            "agent_llm_error": decision.llm_error or "",
        }
