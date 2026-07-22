from __future__ import annotations

import difflib
import json
import re
from typing import Any


MESSAGE_COLUMN = "message"
ALLOWED_COMPLAINT_CATEGORIES = [
    "AC Not Working",
    "Accident on the Way",
    "Bad Driver Behaviour/Skill",
    "Cab Breakdown",
    "Cab Delay",
    "Cab Delayed > 15 Minutes",
    "Cab Delayed by 30-60 Minutes",
    "Cab Delayed > 1 Hour",
    "Chauffeur/Vehicle Change",
    "Drunk Driver",
    "Extra Money Taken",
    "Low Category Vehicle",
    "Poor Vehicle Condition",
    "Vendor No Show",
    "White Number Plate",
]

CAB_DELAY_CATEGORIES = {
    "Cab Delay",
    "Cab Delayed > 15 Minutes",
    "Cab Delayed by 30-60 Minutes",
    "Cab Delayed > 1 Hour",
}


def normalize_category_key(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_CANONICAL_BY_KEY = {normalize_category_key(category): category for category in ALLOWED_COMPLAINT_CATEGORIES}
_ALIASES = {
    "ac not working": "AC Not Working",
    "a c not working": "AC Not Working",
    "air conditioning not working": "AC Not Working",
    "air conditioner not working": "AC Not Working",
    "accident": "Accident on the Way",
    "accident on way": "Accident on the Way",
    "bad driver behavior": "Bad Driver Behaviour/Skill",
    "bad driver behaviour": "Bad Driver Behaviour/Skill",
    "driver behavior": "Bad Driver Behaviour/Skill",
    "driver behaviour": "Bad Driver Behaviour/Skill",
    "driver skill": "Bad Driver Behaviour/Skill",
    "cab breakdown": "Cab Breakdown",
    "vehicle breakdown": "Cab Breakdown",
    "car breakdown": "Cab Breakdown",
    "breakdown": "Cab Breakdown",
    "cab delayed": "Cab Delay",
    "cab delay": "Cab Delay",
    "cab delayed 1 hour": "Cab Delayed > 1 Hour",
    "cab delayed over 1 hour": "Cab Delayed > 1 Hour",
    "cab delayed more than 1 hour": "Cab Delayed > 1 Hour",
    "chauffeur vehicle change": "Chauffeur/Vehicle Change",
    "chauffeur change": "Chauffeur/Vehicle Change",
    "vehicle change": "Chauffeur/Vehicle Change",
    "driver change": "Chauffeur/Vehicle Change",
    "details change": "Chauffeur/Vehicle Change",
    "drunk driver": "Drunk Driver",
    "extra money": "Extra Money Taken",
    "extra money taken": "Extra Money Taken",
    "extra cash": "Extra Money Taken",
    "lower category vehicle": "Low Category Vehicle",
    "low category vehicle": "Low Category Vehicle",
    "poor vehicle condition": "Poor Vehicle Condition",
    "bad vehicle condition": "Poor Vehicle Condition",
    "vendor no show": "Vendor No Show",
    "no show": "Vendor No Show",
    "fulfillment not done": "Vendor No Show",
    "fulfilment not done": "Vendor No Show",
    "white number plate": "White Number Plate",
}
_CANONICAL_BY_KEY.update({normalize_category_key(alias): category for alias, category in _ALIASES.items()})


def build_message_classification_prompt(*, sub_category: str, remarks: str, comments: str) -> str:
    primary_source = "comments" if comments.strip() else "remarks"
    return "\n".join(
        [
            "Complaint category classification task.",
            "Classify the complaint into one or more categories from the allowed list only.",
            "Return only strict JSON in this exact shape: {\"categories\": [\"Category\"]}",
            "Do not return any category that is not in the allowed list.",
            "Use comments as the primary evidence when present. If comments are empty, use remarks.",
            "Use Sub Category only as supporting context; never let it override the primary evidence.",
            "Handle casing differences, minor spelling mistakes, abbreviations, and local wording before deciding.",
            "If the primary evidence does not map to an allowed category, return {\"categories\": []}.",
            (
                "For cab delay, choose Cab Delayed > 1 Hour when the primary evidence says "
                "the delay was more than 1 hour or more than 60 minutes."
            ),
            (
                "For cab delay, choose Cab Delayed by 30-60 Minutes only when the primary evidence "
                "explicitly says 30-60 minutes or a delay from 30 through 60 minutes."
            ),
            (
                "Choose Cab Delayed > 15 Minutes only when the primary evidence explicitly says "
                "a delay greater than 15 minutes and it is not a 30-60 minute or >1 hour window."
            ),
            "If cab delay is present without a clear matching duration window, choose Cab Delay.",
            "For multiple complaint categories, include every matching allowed category.",
            "",
            "Allowed categories:",
            json.dumps(ALLOWED_COMPLAINT_CATEGORIES, ensure_ascii=True),
            "",
            f"Primary evidence source: {primary_source}",
            f"Sub Category: {sub_category}",
            f"Remarks: {remarks}",
            f"Comments: {comments}",
        ]
    )


def build_message_repair_prompt(
    *,
    sub_category: str,
    remarks: str,
    comments: str,
    previous_response: str,
    failure_reason: str,
) -> str:
    primary_source = "comments" if comments.strip() else "remarks"
    primary_text = comments.strip() or remarks.strip()
    return "\n".join(
        [
            "Complaint category classification task.",
            "Repair a previous complaint category classification that could not be used.",
            "Return only strict JSON in this exact shape: {\"categories\": [\"Category\"]}",
            "Use only categories from the allowed list. Do not return any other label.",
            "Use comments as the primary evidence when present. If comments are empty, use remarks.",
            "Use Remarks and Sub Category only as supporting context for spelling, wording, and disambiguation.",
            "Handle casing differences, minor spelling mistakes, abbreviations, and local wording before deciding.",
            "Do not guess from Sub Category when the primary evidence is unrelated, vague, or not a complaint.",
            "If the primary evidence still cannot be mapped to an allowed category, return {\"categories\": []}.",
            (
                "For cab delay, choose Cab Delayed > 1 Hour when the primary evidence says "
                "the delay was more than 1 hour or more than 60 minutes."
            ),
            (
                "For cab delay, choose Cab Delayed by 30-60 Minutes only when the primary evidence "
                "explicitly says 30-60 minutes or a delay from 30 through 60 minutes."
            ),
            (
                "Choose Cab Delayed > 15 Minutes only when the primary evidence explicitly says "
                "a delay greater than 15 minutes and it is not a 30-60 minute or >1 hour window."
            ),
            "If cab delay is present without a clear matching duration window, choose Cab Delay.",
            "For multiple complaint categories, include every matching allowed category.",
            "",
            "Allowed categories:",
            json.dumps(ALLOWED_COMPLAINT_CATEGORIES, ensure_ascii=True),
            "",
            f"Previous failure reason: {failure_reason}",
            f"Previous response: {previous_response[:1000]}",
            f"Primary evidence source: {primary_source}",
            f"Primary evidence text: {primary_text}",
            f"Sub Category: {sub_category}",
            f"Remarks: {remarks}",
            f"Comments: {comments}",
        ]
    )


def build_text_category_classification_prompt(*, source_label: str, text: str) -> str:
    return "\n".join(
        [
            "Complaint category classification task.",
            f"Classify the {source_label} text into one or more categories from the allowed list only.",
            "Return only strict JSON in this exact shape: {\"categories\": [\"Category\"]}",
            "Do not return any category that is not in the allowed list.",
            "Handle casing differences, minor spelling mistakes, abbreviations, and local wording before deciding.",
            (
                "If the text is vague, operational, or cannot be mapped to an allowed category, "
                "return {\"categories\": []}."
            ),
            (
                "For cab delay, choose Cab Delayed > 1 Hour when the text says the delay was "
                "more than 1 hour or more than 60 minutes."
            ),
            (
                "For cab delay, choose Cab Delayed by 30-60 Minutes only when the text explicitly "
                "says 30-60 minutes or a delay from 30 through 60 minutes."
            ),
            (
                "Choose Cab Delayed > 15 Minutes only when the text explicitly says a delay "
                "greater than 15 minutes and it is not a 30-60 minute or >1 hour window."
            ),
            "If cab delay is present without a clear matching duration window, choose Cab Delay.",
            "For multiple complaint categories, include every matching allowed category.",
            "",
            "Allowed categories:",
            json.dumps(ALLOWED_COMPLAINT_CATEGORIES, ensure_ascii=True),
            "",
            f"{source_label}: {text}",
        ]
    )


def build_message_from_response(
    response: str,
    *,
    sub_category: str,
    remarks: str,
    comments: str,
) -> str:
    categories = parse_message_categories(response)
    categories = normalize_cab_delay_selection(
        categories,
        sub_category=sub_category,
        remarks=remarks,
        comments=comments,
    )
    return format_message_categories(categories)


def build_fallback_message(*, sub_category: str, remarks: str, comments: str) -> str:
    return format_message_categories(
        fallback_message_categories(sub_category=sub_category, remarks=remarks, comments=comments)
    )


def parse_message_categories(response: str) -> list[str]:
    parsed = json.loads(extract_json_text(response))
    raw_categories: Any
    if isinstance(parsed, dict):
        raw_categories = parsed.get("categories", parsed.get("complaint_categories", []))
        if isinstance(raw_categories, str):
            raw_categories = split_category_text(raw_categories)
    elif isinstance(parsed, list):
        raw_categories = parsed
    else:
        raw_categories = []

    if not isinstance(raw_categories, list):
        return []

    return ordered_unique_categories(
        category
        for value in raw_categories
        if (category := canonicalize_category(value))
    )


def extract_json_text(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start != -1 and object_end > object_start:
        return text[object_start : object_end + 1]

    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start != -1 and array_end > array_start:
        return text[array_start : array_end + 1]

    return text


def split_category_text(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*\+\s*|,\s*|\n+", value) if part.strip()]


def canonicalize_category(value: object) -> str:
    key = normalize_category_key(value)
    return _CANONICAL_BY_KEY.get(key, "")


SIMILAR_CATEGORY_CUTOFF = 0.72


def map_complaint_labels(value: object) -> list[str]:
    """Map free-text labels to allowed categories via exact/alias keys, then strict similarity.

    Does **not** fall back to Cab Delay when nothing matches.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return []

    mapped: list[str] = []
    for part in split_category_text(text):
        exact = canonicalize_category(part)
        if exact:
            mapped.append(exact)
            continue
        fuzzy = similar_allowed_category(part)
        if fuzzy:
            mapped.append(fuzzy)
    if mapped:
        return ordered_unique_categories(mapped)

    # Whole-string pass (e.g. "FULFILLMENT NOT DONE" as one token).
    exact = canonicalize_category(text)
    if exact:
        return [exact]
    fuzzy = similar_allowed_category(text)
    return [fuzzy] if fuzzy else []


def similar_allowed_category(value: object) -> str:
    normalized_value = normalize_category_key(value)
    if not normalized_value:
        return ""
    choices = {normalize_category_key(category): category for category in ALLOWED_COMPLAINT_CATEGORIES}
    # Also match against alias keys so near-misses like "fulfillment not doen" resolve.
    alias_keys = list(_CANONICAL_BY_KEY.keys())
    matches = difflib.get_close_matches(normalized_value, alias_keys, n=1, cutoff=SIMILAR_CATEGORY_CUTOFF)
    if not matches:
        matches = difflib.get_close_matches(normalized_value, list(choices), n=1, cutoff=SIMILAR_CATEGORY_CUTOFF)
        return choices[matches[0]] if matches else ""
    return _CANONICAL_BY_KEY[matches[0]]


def categories_from_message(value: object) -> list[str]:
    text = "" if value is None else str(value).strip()
    if not text:
        return []

    if text.startswith("{") or text.startswith("[") or text.startswith("```"):
        try:
            return parse_message_categories(text)
        except Exception:
            pass

    return ordered_unique_categories(
        category
        for part in split_category_text(text)
        if (category := canonicalize_category(part))
    )


def normalize_cab_delay_selection(
    categories: list[str],
    *,
    sub_category: str,
    remarks: str,
    comments: str,
) -> list[str]:
    if not any(category in CAB_DELAY_CATEGORIES for category in categories):
        return ordered_unique_categories(categories)

    evidence = comments.strip() or remarks.strip()
    delay_category = (
        classify_cab_delay_window(evidence)
        or classify_cab_delay_window(" ".join(part for part in [sub_category, remarks] if part.strip()))
        or "Cab Delay"
    )

    non_delay_categories = [category for category in categories if category not in CAB_DELAY_CATEGORIES]
    return ordered_unique_categories([*non_delay_categories, delay_category])


def fallback_message_categories(*, sub_category: str, remarks: str, comments: str) -> list[str]:
    primary_text = comments.strip() or remarks.strip()
    categories = infer_categories_from_text(primary_text)
    if categories:
        return categories

    categories = infer_categories_from_text(" ".join(part for part in [remarks, sub_category] if part.strip()))
    if categories:
        return categories

    for value in [sub_category, remarks, primary_text]:
        category = canonicalize_category(value)
        if category:
            return [category]

    return [closest_allowed_category(" ".join(part for part in [sub_category, remarks, primary_text] if part.strip()))]


def infer_categories_from_text(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []

    normalized = normalize_category_key(text)
    categories: list[str] = []

    delay_category = classify_cab_delay_window(text)
    if delay_category:
        categories.append(delay_category)

    if re.search(r"\b(?:a\s*/?\s*c|ac|air condition(?:er|ing)?)\b.*\b(?:not working|failed|issue|problem)\b", normalized):
        categories.append("AC Not Working")
    if re.search(r"\b(?:accident|crash|collision)\b", normalized):
        categories.append("Accident on the Way")
    if re.search(r"\b(?:rude|misbehav|abusive|rash|unsafe|bad driver|driver skill|driver behaviour|driver behavior)\b", normalized):
        categories.append("Bad Driver Behaviour/Skill")
    if re.search(r"\b(?:breakdown|broke down|vehicle stopped|cab stopped|car stopped)\b", normalized):
        categories.append("Cab Breakdown")
    if re.search(r"\b(?:chauffeur change|driver change|vehicle change|cab change|car change|details change)\b", normalized):
        categories.append("Chauffeur/Vehicle Change")
    if re.search(r"\b(?:drunk|intoxicated|alcohol)\b", normalized):
        categories.append("Drunk Driver")
    if re.search(r"\b(?:extra money|extra cash|collected extra|charged extra|extra charge|overcharg|toll and parking)\b", normalized):
        categories.append("Extra Money Taken")
    if re.search(r"\b(?:low category|lower category|downgrad|booked .* received|received .* instead)\b", normalized):
        categories.append("Low Category Vehicle")
    if re.search(r"\b(?:poor vehicle condition|bad vehicle condition|dirty|unclean|damaged|smell|stink)\b", normalized):
        categories.append("Poor Vehicle Condition")
    if re.search(r"\b(?:vendor no show|no show|cab did not arrive|cab didn t arrive|assigned cab did not arrive)\b", normalized):
        categories.append("Vendor No Show")
    if re.search(r"\b(?:white number plate|private number plate|white plate)\b", normalized):
        categories.append("White Number Plate")

    return ordered_unique_categories(categories)


def classify_cab_delay_window(value: str) -> str:
    normalized = normalize_category_key(value)
    if not mentions_delay(normalized):
        return ""

    durations = extract_delay_durations_minutes(normalized)
    if mentions_delay_over_one_hour(value, normalized) or any(duration > 60 for duration in durations):
        return "Cab Delayed > 1 Hour"

    if re.search(r"\b30\s*(?:to|-)\s*60\s*(?:min|mins|minute|minutes)?\b", normalized):
        return "Cab Delayed by 30-60 Minutes"
    if re.search(r"\b(?:half an hour|an hour|one hour|1 hour)\b", normalized):
        return "Cab Delayed by 30-60 Minutes"

    if any(30 <= duration <= 60 for duration in durations):
        return "Cab Delayed by 30-60 Minutes"
    if any(duration > 15 for duration in durations):
        return "Cab Delayed > 15 Minutes"

    if re.search(r"\b(?:more than|over|greater than|above)\s*15\s*(?:min|mins|minute|minutes)?\b", normalized):
        return "Cab Delayed > 15 Minutes"
    if re.search(r"(?:>\s*15|15\s*\+)\s*(?:min|mins|minute|minutes)?", value.casefold()):
        return "Cab Delayed > 15 Minutes"

    return "Cab Delay"


def extract_delay_durations_minutes(normalized_text: str) -> list[float]:
    combined_values = [
        (float(hours) * 60) + float(minutes)
        for hours, minutes in re.findall(
            r"\b(\d+(?:\.\d+)?)\s*(?:hr|hrs|hour|hours)\s*(?:and\s*)?(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes)\b",
            normalized_text,
        )
    ]
    minute_values = [
        float(match)
        for match in re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes)\b", normalized_text)
    ]
    hour_values = [
        float(match) * 60
        for match in re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:hr|hrs|hour|hours)\b", normalized_text)
    ]
    return [*combined_values, *minute_values, *hour_values]


def mentions_delay_over_one_hour(raw_text: str, normalized_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:more than|over|greater than|above)\s*(?:1|one|an)\s*(?:hr|hrs|hour|hours)\b",
            normalized_text,
        )
        or re.search(
            r"\b(?:more than|over|greater than|above)\s*60\s*(?:min|mins|minute|minutes)\b",
            normalized_text,
        )
        or re.search(r"(?:>\s*(?:1|one)\s*(?:hr|hrs|hour|hours)|(?:1|one)\s*(?:hr|hrs|hour|hours)\s*\+)", raw_text.casefold())
        or re.search(r"(?:>\s*60\s*(?:min|mins|minute|minutes)|60\s*(?:min|mins|minute|minutes)\s*\+)", raw_text.casefold())
    )


def mentions_delay(normalized_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:cab delay|cab delayed|delayed|delay|late|waiting|waited|needed \d+|need \d+)\b",
            normalized_text,
        )
    )


def closest_allowed_category(value: str) -> str:
    normalized_value = normalize_category_key(value)
    if not normalized_value:
        return "Cab Delay"

    choices = {normalize_category_key(category): category for category in ALLOWED_COMPLAINT_CATEGORIES}
    matches = difflib.get_close_matches(normalized_value, list(choices), n=1, cutoff=0.35)
    return choices[matches[0]] if matches else "Cab Delay"


def ordered_unique_categories(categories: list[str] | Any) -> list[str]:
    selected = {category for category in categories if category in ALLOWED_COMPLAINT_CATEGORIES}
    return [category for category in ALLOWED_COMPLAINT_CATEGORIES if category in selected]


def format_message_categories(categories: list[str]) -> str:
    return " + ".join(ordered_unique_categories(categories))
