from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.app.agents.llm import AgentLlmGenerator, maybe_call_agent_llm
from backend.app.agents.models import ClaimCase, clean_text, json_safe
from backend.app.domain.complaint_message import (
    CAB_DELAY_CATEGORIES,
    build_text_category_classification_prompt,
    categories_from_message,
    format_message_categories,
    normalize_cab_delay_selection,
    ordered_unique_categories,
    parse_message_categories,
)


PrimarySource = Literal["comments", "remarks", ""]
ComparisonSource = Literal["remarks", "sub_category", "remarks_or_sub_category", ""]
AlignmentStatus = Literal[
    "aligned",
    "category_mismatch",
    "booking_id_mismatch",
    "invalid_signal",
    "missing_evidence",
]

SOURCE_LABELS = {
    "comments": "comments",
    "remarks": "Remarks",
    "sub_category": "Sub Category",
}
INVALID_PENALTY_PATTERN = re.compile(
    (
        r"\b(no complaint|no issue|issue resolved|complaint resolved|wrong penalty|"
        r"incorrect penalty|false claim|invalid penalty|penalty not valid|not genuine|"
        r"customer denied|denied complaint)\b"
    ),
    re.I,
)
REAL_BOOKING_ID_PATTERN = re.compile(r"\b((?:NC|NCI|CARP)\d{6,})\b", re.I)


@dataclass(frozen=True)
class SourceAlignment:
    primary_source: PrimarySource
    source_label: str
    source_text: str
    source_evidence_id: str
    source_categories: list[str]
    row_categories: list[str]
    comments_categories: list[str] = field(default_factory=list)
    remarks_categories: list[str] = field(default_factory=list)
    sub_category_categories: list[str] = field(default_factory=list)
    comparison_source: ComparisonSource = ""
    comparison_label: str = ""
    comparison_text: str = ""
    mentioned_booking_ids: list[str] = field(default_factory=list)
    status: AlignmentStatus = "missing_evidence"
    review_status: Literal["auto_ready", "needs_review", "missing_evidence"] = "missing_evidence"
    reason: str = ""

    @property
    def message(self) -> str:
        return format_message_categories(self.source_categories)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_source": self.primary_source,
            "source_label": self.source_label,
            "source_text": self.source_text,
            "source_evidence_id": self.source_evidence_id,
            "source_categories": self.source_categories,
            "row_categories": self.row_categories,
            "comments_categories": self.comments_categories,
            "remarks_categories": self.remarks_categories,
            "sub_category_categories": self.sub_category_categories,
            "comparison_source": self.comparison_source,
            "comparison_label": self.comparison_label,
            "comparison_text": self.comparison_text,
            "mentioned_booking_ids": self.mentioned_booking_ids,
            "status": self.status,
            "review_status": self.review_status,
            "reason": self.reason,
            "message": self.message,
        }


def build_source_alignment(case: ClaimCase) -> SourceAlignment:
    return build_source_alignment_from_categories(
        case,
        remarks_categories=[],
        sub_category_categories=[],
        row_classification_error="LLM row-context classification was not run.",
    )


async def build_source_alignment_async(
    case: ClaimCase,
    *,
    llm_generator: AgentLlmGenerator,
    semaphore,
) -> SourceAlignment:
    comments = clean_text(case.comments)
    remarks = clean_text(case.remarks)
    sub_category = clean_text(case.sub_category)
    comparison_items = comparison_contexts(remarks, sub_category)
    remarks_categories: list[str] = []
    sub_category_categories: list[str] = []
    classification_errors: list[str] = []

    if comparison_items and (comments or remarks):
        for comparison_source, comparison_label, comparison_text in comparison_items:
            try:
                categories = await classify_comparison_categories(
                    source_label=comparison_label,
                    text=comparison_text,
                    llm_generator=llm_generator,
                    semaphore=semaphore,
                )
            except Exception:
                categories = []
                classification_errors.append(f"{comparison_label} could not be classified by the LLM.")
            if comparison_source == "remarks":
                remarks_categories = categories
            elif comparison_source == "sub_category":
                sub_category_categories = categories

    return build_source_alignment_from_categories(
        case,
        remarks_categories=remarks_categories,
        sub_category_categories=sub_category_categories,
        row_classification_error="; ".join(classification_errors),
    )


def build_source_alignment_from_categories(
    case: ClaimCase,
    *,
    remarks_categories: list[str],
    sub_category_categories: list[str],
    row_classification_error: str = "",
    comparison_source: ComparisonSource | None = None,
    comparison_label: str = "",
    comparison_text: str = "",
) -> SourceAlignment:
    comments = clean_text(case.comments)
    remarks = clean_text(case.remarks)
    sub_category = clean_text(case.sub_category)
    message_categories = categories_from_message(case.message)
    if comparison_source is None:
        comparison_source, comparison_label, comparison_text = combined_comparison_context(remarks, sub_category)

    comments_categories = message_categories if comments else []
    row_categories = ordered_unique_categories([*remarks_categories, *sub_category_categories])

    if comments:
        primary_source: PrimarySource = "comments"
        source_text = comments
        source_categories = message_categories
    elif remarks:
        primary_source = "remarks"
        source_text = remarks
        source_categories = message_categories
    else:
        return SourceAlignment(
            primary_source="",
            source_label="No source",
            source_text="",
            source_evidence_id="",
            source_categories=[],
            row_categories=[],
            comments_categories=comments_categories,
            remarks_categories=remarks_categories,
            sub_category_categories=sub_category_categories,
            comparison_source=comparison_source,
            comparison_label=comparison_label,
            comparison_text=comparison_text,
            status="missing_evidence",
            review_status="missing_evidence",
            reason="No comments or Remarks were available; Sub Category alone is not enough for agent recovery.",
        )

    source_label = SOURCE_LABELS[primary_source]
    source_evidence_id = f"{case.booking_id}:{primary_source}"
    mentioned_booking_ids = extract_booking_ids(source_text)
    booking_mismatch = has_booking_id_mismatch(case.booking_id, mentioned_booking_ids)
    invalid_signal = bool(INVALID_PENALTY_PATTERN.search(source_text))

    if booking_mismatch:
        status: AlignmentStatus = "booking_id_mismatch"
        review_status: Literal["auto_ready", "needs_review", "missing_evidence"] = "needs_review"
        reason = (
            f"{source_label} mention booking {', '.join(mentioned_booking_ids)}, "
            f"which does not match row booking {case.booking_id or 'unknown'}."
        )
    elif invalid_signal:
        status = "invalid_signal"
        review_status = "needs_review"
        reason = f"{source_label} contains a denied, resolved, or invalid-penalty signal."
    elif not source_categories:
        status = "category_mismatch"
        review_status = "needs_review"
        reason = "message could not be mapped to an allowed complaint category."
    elif not row_categories:
        status = "category_mismatch"
        review_status = "needs_review"
        reason = (
            row_classification_error
            or f"{comparison_label or 'row context'} could not be mapped to an allowed complaint category."
        )
    elif not any_category_overlap(source_categories, remarks_categories, sub_category_categories):
        status = "category_mismatch"
        review_status = "needs_review"
        reason = (
            f"message indicates {format_categories(source_categories)}, "
            f"but {comparison_label} indicates {format_categories(row_categories)}."
        )
    else:
        status = "aligned"
        review_status = "auto_ready"
        reason = build_aligned_reason("message", source_categories, row_categories, comparison_label=comparison_label)

    return SourceAlignment(
        primary_source=primary_source,
        source_label=source_label,
        source_text=source_text,
        source_evidence_id=source_evidence_id,
        source_categories=source_categories,
        row_categories=row_categories,
        comments_categories=comments_categories,
        remarks_categories=remarks_categories,
        sub_category_categories=sub_category_categories,
        comparison_source=comparison_source,
        comparison_label=comparison_label,
        comparison_text=comparison_text,
        mentioned_booking_ids=mentioned_booking_ids,
        status=status,
        review_status=review_status,
        reason=reason,
    )


async def classify_comparison_categories(
    *,
    source_label: str,
    text: str,
    llm_generator: AgentLlmGenerator,
    semaphore,
) -> list[str]:
    prompt = build_text_category_classification_prompt(source_label=source_label, text=text)
    response = await maybe_call_agent_llm(
        llm_generator,
        prompt,
        max_completion_tokens=2048,
        reasoning_effort="minimal",
        semaphore=semaphore,
    )
    categories = parse_message_categories(response)
    return normalize_cab_delay_selection(categories, sub_category="", remarks=text, comments="")


def comparison_contexts(remarks: str, sub_category: str) -> list[tuple[ComparisonSource, str, str]]:
    contexts: list[tuple[ComparisonSource, str, str]] = []
    if clean_text(remarks):
        contexts.append(("remarks", "Remarks", clean_text(remarks)))
    if clean_text(sub_category):
        contexts.append(("sub_category", "Sub Category", clean_text(sub_category)))
    return contexts


def combined_comparison_context(remarks: str, sub_category: str) -> tuple[ComparisonSource, str, str]:
    contexts = comparison_contexts(remarks, sub_category)
    if len(contexts) == 2:
        return (
            "remarks_or_sub_category",
            "Remarks or Sub Category",
            f"Remarks: {contexts[0][2]}\nSub Category: {contexts[1][2]}",
        )
    if contexts:
        return contexts[0]
    return "", "", ""


def category_overlap(left: list[str], right: list[str]) -> bool:
    left_set = set(left)
    right_set = set(right)
    return bool(left_set & right_set) or bool(left_set & CAB_DELAY_CATEGORIES and right_set & CAB_DELAY_CATEGORIES)


def any_category_overlap(source_categories: list[str], *comparison_groups: list[str]) -> bool:
    return any(category_overlap(source_categories, categories) for categories in comparison_groups if categories)


def build_aligned_reason(
    source_label: str,
    source_categories: list[str],
    row_categories: list[str],
    *,
    comparison_label: str,
) -> str:
    source_message = format_categories(source_categories)
    if not row_categories:
        return f"{source_label} supports {source_message}; no conflicting row category was available."

    row_message = format_categories(row_categories)
    extra_categories = [category for category in source_categories if category not in row_categories]
    if extra_categories:
        return (
            f"{source_label} supports {row_message} and also mentions "
            f"{format_categories(extra_categories)} in addition to {comparison_label}."
        )
    return f"{source_label} supports {comparison_label} category {row_message}."


def extract_booking_ids(text: str) -> list[str]:
    values: list[str] = []
    for match in REAL_BOOKING_ID_PATTERN.findall(text):
        booking_id = clean_booking_id(match)
        if booking_id and booking_id not in values:
            values.append(booking_id)
    return values


def has_booking_id_mismatch(case_booking_id: str, mentioned_booking_ids: list[str]) -> bool:
    if not mentioned_booking_ids:
        return False

    case_key = booking_id_key(case_booking_id)
    if not case_key:
        return True
    return any(booking_id_key(booking_id) != case_key for booking_id in mentioned_booking_ids)


def clean_booking_id(value: str) -> str:
    return clean_text(value).strip(".,;:()[]{}")


def booking_id_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", clean_text(value)).casefold()


def format_categories(categories: list[str]) -> str:
    return format_message_categories(categories) or "no allowed category"


def source_analysis_text(source_analysis: dict[str, Any], key: str) -> str:
    value = source_analysis.get(key)
    if isinstance(value, list):
        return format_message_categories([str(item) for item in value])
    return clean_text(value)


def compact_source_analysis(source_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary_source": clean_text(source_analysis.get("primary_source")),
        "source_label": clean_text(source_analysis.get("source_label")),
        "source_categories": json_safe(source_analysis.get("source_categories", [])),
        "row_categories": json_safe(source_analysis.get("row_categories", [])),
        "comparison_source": clean_text(source_analysis.get("comparison_source")),
        "comparison_label": clean_text(source_analysis.get("comparison_label")),
        "status": clean_text(source_analysis.get("status")),
        "review_status": clean_text(source_analysis.get("review_status")),
        "reason": clean_text(source_analysis.get("reason")),
        "message": clean_text(source_analysis.get("message")),
        "mentioned_booking_ids": json_safe(source_analysis.get("mentioned_booking_ids", [])),
    }
