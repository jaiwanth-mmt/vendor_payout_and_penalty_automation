from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import httpx

from backend.app.core.env import DEFAULT_ENV_PATH, load_env_file
from backend.app.core.paths import DEMO_EXPECTED_OUTPUT_PATH, DEMO_TRACKING_JSON_PATH


DEFAULT_INPUT_PATH = DEMO_EXPECTED_OUTPUT_PATH
DEFAULT_TRACKING_JSON_PATH = DEMO_TRACKING_JSON_PATH
PREFERRED_START_TIME_IST_COLUMN = "Customer preferred pickup time (IST)"
DRIVER_STARTED_COLUMN = "Driver started towards pickup (IST)"
DRIVER_ARRIVED_COLUMN = "Driver arrived at pickup (IST)"
BOARDED_COLUMN = "Customer boarded cab (IST)"
INCABS_INSIGHT_COLUMN = "insights from incabs data"
COMMENTS_COLUMN = "comments"
INCABS_COMMENT_SUMMARY_COLUMN = "incabs and customer comment summary"
CAB_DELAY_ENRICHMENT_COLUMNS = [
    PREFERRED_START_TIME_IST_COLUMN,
    DRIVER_STARTED_COLUMN,
    DRIVER_ARRIVED_COLUMN,
    BOARDED_COLUMN,
    INCABS_INSIGHT_COLUMN,
    COMMENTS_COLUMN,
    INCABS_COMMENT_SUMMARY_COLUMN,
]
DEFAULT_MAX_COMPLETION_TOKENS = 512
DEFAULT_REASONING_EFFORT = "minimal"
IST_OFFSET = timedelta(hours=5, minutes=30)
CAB_DELAY_PATTERN = re.compile(r"\bcab\s+(?:delay|delayed|dealy)\b", re.IGNORECASE)
NON_CAB_DELAY_REMARK_TOKEN_PATTERN = re.compile(
    r"\bcab\s+(?:delay|delayed|dealy)\b|[/,+&]|\band\b|\s+",
    re.IGNORECASE,
)
MISSING_TIME_VALUES = {"", "0", "none", "nan", "nat", "null"}
OUTPUT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DISPLAY_DATETIME_FORMAT = "%d %b %Y %I:%M %p"
DISPLAY_DATETIME_WITH_SECONDS_FORMAT = "%d %b %Y %I:%M:%S %p"


@dataclass(frozen=True)
class TimingContext:
    scheduled_pickup_ist: datetime | None
    driver_started: datetime | None
    driver_arrived: datetime | None
    boarded: datetime | None


@dataclass(frozen=True)
class TrackingEnrichment:
    preferred_start_time_ist: str
    driver_started: str
    driver_arrived: str
    boarded: str
    comments: str

    def to_columns(self) -> dict[str, str]:
        return {
            PREFERRED_START_TIME_IST_COLUMN: self.preferred_start_time_ist,
            DRIVER_STARTED_COLUMN: self.driver_started,
            DRIVER_ARRIVED_COLUMN: self.driver_arrived,
            BOARDED_COLUMN: self.boarded,
            COMMENTS_COLUMN: self.comments,
        }


def parse_args() -> argparse.Namespace:
    load_env_file()

    parser = argparse.ArgumentParser(
        description="Generate business-readable cab-delay insights using tracking timings and Azure OpenAI."
    )
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--tracking-json-path", type=Path, default=DEFAULT_TRACKING_JSON_PATH)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Regenerate non-empty Incabs insight values.")
    parser.add_argument("--dry-run", action="store_true", help="Show target rows and computed timings without calling LLM.")
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=DEFAULT_MAX_COMPLETION_TOKENS,
        help="Azure OpenAI completion token budget. GPT-5 may use part of this for reasoning.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=DEFAULT_REASONING_EFFORT,
        choices=["minimal", "low", "medium", "high"],
        help="GPT-5 reasoning effort for Azure OpenAI chat completions.",
    )
    return parser.parse_args()


def contains_cab_delay(value: object) -> bool:
    if pd.isna(value):
        return False
    return bool(CAB_DELAY_PATTERN.search(str(value)))


def is_pure_cab_delay_remark(value: object) -> bool:
    if pd.isna(value):
        return False

    raw_value = str(value).strip()
    if not raw_value or not contains_cab_delay(raw_value):
        return False

    leftover = NON_CAB_DELAY_REMARK_TOKEN_PATTERN.sub("", raw_value).strip()
    return leftover == ""


def parse_tracking_time(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if text.casefold() in MISSING_TIME_VALUES:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_start_time_utc(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if text.casefold() in MISSING_TIME_VALUES:
        return ""
    return text


def raw_tracking_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "unavailable"
    return value.strftime(OUTPUT_DATETIME_FORMAT)


def format_display_time(value: datetime | None) -> str:
    if value is None:
        return ""
    format_string = DISPLAY_DATETIME_WITH_SECONDS_FORMAT if value.second else DISPLAY_DATETIME_FORMAT
    return value.strftime(format_string).replace(" 0", " ", 1)


def format_ist_from_utc(value: Any) -> str:
    parsed_value = parse_tracking_time(value)
    if parsed_value is None:
        return ""
    return format_display_time(parsed_value + IST_OFFSET)


def format_existing_ist_time(value: Any) -> str:
    return format_display_time(parse_tracking_time(value))


def duration_minutes(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60)


def format_duration(value: int | None) -> str:
    if value is None:
        return "unavailable"

    sign = "-" if value < 0 else ""
    absolute_value = abs(value)
    hours, minutes = divmod(absolute_value, 60)
    if hours:
        return f"{sign}{hours} hr {minutes} min"
    return f"{sign}{minutes} min"


def read_tracking_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")).get("bookings", {})


def booking_comments(bookings: dict[str, Any], booking_id: str) -> str:
    booking = bookings.get(booking_id, {})
    if not isinstance(booking, dict):
        return ""

    value = booking.get("comments")
    if value is None or str(value).strip() == "":
        value = booking.get("comment")
    return raw_tracking_value(value)


def first_tracking_row(bookings: dict[str, Any], booking_id: str) -> dict[str, Any]:
    rows = bookings.get(booking_id, {}).get("tracking_reports_raw", [])
    if not rows:
        return {}
    return rows[0]


def build_tracking_enrichment(bookings: dict[str, Any], booking_id: str) -> TrackingEnrichment:
    tracking_row = first_tracking_row(bookings, booking_id)

    return TrackingEnrichment(
        preferred_start_time_ist=format_ist_from_utc(tracking_row.get("start_time")),
        driver_started=format_existing_ist_time(tracking_row.get("driver_started")),
        driver_arrived=format_existing_ist_time(tracking_row.get("driver_arrived")),
        boarded=format_existing_ist_time(tracking_row.get("boarded")),
        comments=booking_comments(bookings, booking_id),
    )


def build_timing_context(tracking_row: dict[str, Any]) -> TimingContext:
    start_time_utc = parse_tracking_time(tracking_row.get("start_time"))
    return TimingContext(
        scheduled_pickup_ist=start_time_utc + IST_OFFSET if start_time_utc else None,
        driver_started=parse_tracking_time(tracking_row.get("driver_started")),
        driver_arrived=parse_tracking_time(tracking_row.get("driver_arrived")),
        boarded=parse_tracking_time(tracking_row.get("boarded")),
    )


def build_incabs_insight_prompt(booking_id: str, timing: TimingContext) -> str:
    pickup_to_start = duration_minutes(timing.scheduled_pickup_ist, timing.driver_started)
    pickup_to_arrival = duration_minutes(timing.scheduled_pickup_ist, timing.driver_arrived)
    pickup_to_boarding = duration_minutes(timing.scheduled_pickup_ist, timing.boarded)
    start_to_arrival = duration_minutes(timing.driver_started, timing.driver_arrived)
    arrival_to_boarding = duration_minutes(timing.driver_arrived, timing.boarded)

    return "\n".join(
        [
            "Write one short, business-friendly Incabs insight explaining this cab delay.",
            "Do not mention UTC, JSON, APIs, fields, or technical system names.",
            "Use the calculated delays as facts. If a timestamp is unavailable, say the available evidence only.",
            "Keep it to one sentence, under 45 words.",
            "",
            f"Booking ID: {booking_id}",
            f"Scheduled pickup time: {format_dt(timing.scheduled_pickup_ist)}",
            f"Driver started time: {format_dt(timing.driver_started)}",
            f"Driver arrived time: {format_dt(timing.driver_arrived)}",
            f"Customer boarded time: {format_dt(timing.boarded)}",
            f"Driver started after scheduled pickup: {format_duration(pickup_to_start)}",
            f"Driver arrived after scheduled pickup: {format_duration(pickup_to_arrival)}",
            f"Customer boarded after scheduled pickup: {format_duration(pickup_to_boarding)}",
            f"Driver travel time from start to arrival: {format_duration(start_to_arrival)}",
            f"Customer wait after driver arrival: {format_duration(arrival_to_boarding)}",
        ]
    )


def build_comment_summary_prompt(
    *,
    booking_id: str,
    incabs_insight: str,
    comments: str,
    preferred_start_time_ist: str,
) -> str:
    return "\n".join(
        [
            "Write one brief business-friendly summary comparing Incabs tracking data with the customer call comment.",
            "Explain what Incabs says and what the customer reported, without choosing a side unless the facts clearly show it.",
            "Prefer IST timing for readability. Do not mention JSON, APIs, fields, prompts, or technical system names.",
            "Keep it to one sentence, under 55 words.",
            "",
            f"Booking ID: {booking_id}",
            f"Preferred pickup time (IST): {preferred_start_time_ist or 'unavailable'}",
            f"Incabs insight: {incabs_insight or 'unavailable'}",
            f"Customer call comment: {comments or 'unavailable'}",
        ]
    )


def call_azure_openai(prompt: str, max_completion_tokens: int, reasoning_effort: str) -> str:
    api_url = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not api_url or not api_key:
        raise ValueError("AZURE_OPENAI_CHAT_COMPLETIONS_URL and AZURE_OPENAI_API_KEY are required in .env.")

    payload = {
        "messages": [
            {
                "role": "system",
                "content": "You write concise operational explanations for non-technical business users.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": reasoning_effort,
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI request failed with HTTP {error.code}: {error_body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Azure OpenAI request failed: {error.reason}") from error

    choices = response_payload.get("choices", [])
    if not choices:
        raise RuntimeError(f"Azure OpenAI returned no choices: {response_payload}")

    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError(f"Azure OpenAI returned an empty message: {response_payload}")

    return " ".join(content.strip().split())


async def call_azure_openai_async(prompt: str, max_completion_tokens: int, reasoning_effort: str) -> str:
    api_url = os.getenv("AZURE_OPENAI_CHAT_COMPLETIONS_URL")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if not api_url or not api_key:
        raise ValueError("AZURE_OPENAI_CHAT_COMPLETIONS_URL and AZURE_OPENAI_API_KEY are required in .env.")

    payload = {
        "messages": [
            {
                "role": "system",
                "content": "You write concise operational explanations for non-technical business users.",
            },
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": reasoning_effort,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "api-key": api_key,
                },
            )
            response.raise_for_status()
            response_payload = response.json()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(
            f"Azure OpenAI request failed with HTTP {error.response.status_code}: {error.response.text}"
        ) from error
    except httpx.RequestError as error:
        raise RuntimeError(f"Azure OpenAI request failed: {error}") from error

    choices = response_payload.get("choices", [])
    if not choices:
        raise RuntimeError(f"Azure OpenAI returned no choices: {response_payload}")

    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError(f"Azure OpenAI returned an empty message: {response_payload}")

    return " ".join(content.strip().split())


def find_target_rows(df: pd.DataFrame) -> pd.Series:
    if "Sub Category" not in df.columns or "Remarks" not in df.columns:
        raise KeyError("Input workbook must contain 'Sub Category' and 'Remarks' columns.")

    mentions_cab_delay = df["Sub Category"].apply(contains_cab_delay) | df["Remarks"].apply(contains_cab_delay)
    pure_cab_delay_remark = df["Remarks"].apply(is_pure_cab_delay_remark)
    return mentions_cab_delay & pure_cab_delay_remark


def ensure_enrichment_columns(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    for column in CAB_DELAY_ENRICHMENT_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    return output


def enrich_insights(args: argparse.Namespace) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    df = pd.read_excel(args.input_path)
    df.columns = [str(column).strip() for column in df.columns]

    if "Booking ID" not in df.columns:
        raise KeyError("Input workbook must contain 'Booking ID'.")

    df = ensure_enrichment_columns(df)
    tracking_bookings = read_tracking_data(args.tracking_json_path)
    for index in df.index.tolist():
        booking_id = str(df.at[index, "Booking ID"]).strip()
        if not booking_id:
            continue
        for column, value in build_tracking_enrichment(tracking_bookings, booking_id).to_columns().items():
            df.at[index, column] = value

    target_mask = find_target_rows(df)
    if not args.force:
        existing_insight = df[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
        target_mask = target_mask & ~existing_insight

    target_indices = df.index[target_mask].tolist()
    generated_booking_ids: list[str] = []
    generated_summary_booking_ids: list[str] = []
    failed_booking_ids: list[str] = []
    failed_summary_booking_ids: list[str] = []
    generated_insights: dict[int, str] = {}
    generated_summaries: dict[int, str] = {}

    for index in target_indices:
        booking_id = str(df.at[index, "Booking ID"]).strip()
        tracking_row = first_tracking_row(tracking_bookings, booking_id)
        timing = build_timing_context(tracking_row)
        prompt = build_incabs_insight_prompt(booking_id, timing)

        if args.dry_run:
            source_start_time_utc = normalize_start_time_utc(tracking_row.get("start_time"))
            print(f"{booking_id}:")
            print(f"  scheduled pickup IST: {format_dt(timing.scheduled_pickup_ist)}")
            print(f"  source start time UTC: {source_start_time_utc or 'unavailable'}")
            print(f"  driver started: {format_dt(timing.driver_started)}")
            print(f"  driver arrived: {format_dt(timing.driver_arrived)}")
            print(f"  boarded: {format_dt(timing.boarded)}")
            print(f"  comments: {df.at[index, COMMENTS_COLUMN] or 'unavailable'}")
            continue

        try:
            generated_insights[index] = call_azure_openai(
                prompt,
                max_completion_tokens=args.max_completion_tokens,
                reasoning_effort=args.reasoning_effort,
            )
            generated_booking_ids.append(booking_id)
        except Exception as error:
            failed_booking_ids.append(booking_id)
            print(f"Failed to generate Incabs insight for {booking_id}: {error}", file=sys.stderr)

    if failed_booking_ids:
        return df, generated_booking_ids, generated_summary_booking_ids, failed_booking_ids

    for index, insight in generated_insights.items():
        df.at[index, INCABS_INSIGHT_COLUMN] = insight

    if not args.dry_run:
        summary_mask = (
            find_target_rows(df)
            & df[INCABS_INSIGHT_COLUMN].fillna("").astype(str).str.strip().ne("")
            & df[COMMENTS_COLUMN].fillna("").astype(str).str.strip().ne("")
        )
        if not args.force:
            existing_summary = df[INCABS_COMMENT_SUMMARY_COLUMN].fillna("").astype(str).str.strip().ne("")
            summary_mask = summary_mask & ~existing_summary

        for index in df.index[summary_mask].tolist():
            booking_id = str(df.at[index, "Booking ID"]).strip()
            prompt = build_comment_summary_prompt(
                booking_id=booking_id,
                incabs_insight=str(df.at[index, INCABS_INSIGHT_COLUMN]).strip(),
                comments=str(df.at[index, COMMENTS_COLUMN]).strip(),
                preferred_start_time_ist=str(df.at[index, PREFERRED_START_TIME_IST_COLUMN]).strip(),
            )
            try:
                generated_summaries[index] = call_azure_openai(
                    prompt,
                    max_completion_tokens=args.max_completion_tokens,
                    reasoning_effort=args.reasoning_effort,
                )
                generated_summary_booking_ids.append(booking_id)
            except Exception as error:
                failed_summary_booking_ids.append(booking_id)
                print(f"Failed to generate Incabs/comment summary for {booking_id}: {error}", file=sys.stderr)

    for index, summary in generated_summaries.items():
        df.at[index, INCABS_COMMENT_SUMMARY_COLUMN] = summary

    if failed_summary_booking_ids:
        print(
            "Incabs/comment summaries were left blank for: " + ", ".join(failed_summary_booking_ids),
            file=sys.stderr,
        )

    return df, generated_booking_ids, generated_summary_booking_ids, failed_booking_ids


def main() -> int:
    args = parse_args()
    output_path = args.output_path or args.input_path

    enriched_df, generated_booking_ids, generated_summary_booking_ids, failed_booking_ids = enrich_insights(args)

    if failed_booking_ids:
        print("No workbook changes were written because Incabs insight LLM calls failed.", file=sys.stderr)
        print("Failed booking IDs: " + ", ".join(failed_booking_ids), file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run complete. No workbook changes were written.")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    enriched_df.to_excel(output_path, index=False)

    print(f"Generated Incabs insights: {len(generated_booking_ids)}")
    print(f"Generated Incabs/comment summaries: {len(generated_summary_booking_ids)}")
    print(f"Saved enriched workbook to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
