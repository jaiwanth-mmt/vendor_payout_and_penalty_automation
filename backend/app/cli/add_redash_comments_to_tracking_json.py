from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
from typing import Any

from backend.app.integrations.tracking_reports import (
    DEFAULT_INPUT_PATH,
    DEFAULT_OUTPUT_PATH,
    load_env_file,
    read_penalty_bookings,
)
from backend.app.integrations.redash_call_comments import (
    DEFAULT_REDASH_BATCH_SIZE,
    DEFAULT_REDASH_HOST,
    DEFAULT_REDASH_SOURCE_IDS,
    fetch_call_comments_for_booking_ids,
    parse_source_ids,
)


def read_booking_ids_from_json(json_path: Path) -> list[str]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    return [str(booking_id).strip() for booking_id in payload.get("bookings", {}) if str(booking_id).strip()]


def read_booking_ids(input_path: Path | None, json_path: Path) -> list[str]:
    if input_path is not None:
        penalty_df = read_penalty_bookings(input_path)
        return penalty_df["Booking ID"].tolist()
    return read_booking_ids_from_json(json_path)


def enrich_json(
    json_path: Path,
    booking_ids: list[str],
    comments_by_booking: dict[str, str],
    redash_metadata: dict[str, Any],
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    bookings = data["bookings"]

    metadata = data.setdefault("metadata", {})
    metadata["commented_booking_count"] = len(comments_by_booking)
    metadata["redash_comments"] = redash_metadata

    updated: list[str] = []
    missing: list[str] = []
    for booking_id in booking_ids:
        booking = bookings.get(booking_id)
        comment = comments_by_booking.get(booking_id, "").strip()
        if booking is None or not comment:
            missing.append(booking_id)
            continue

        if booking.get("comments") != comment:
            booking["comments"] = comment
            updated.append(booking_id)

    if not dry_run:
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return updated, missing


def parse_args() -> argparse.Namespace:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Fetch Redash call transcript comments for workbook booking IDs and add them to tracking JSON."
    )
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument(
        "--use-json-bookings",
        action="store_true",
        help="Read booking IDs from the JSON instead of --input-path.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--redash-api-key", default=os.getenv("REDASH_API_KEY"))
    parser.add_argument("--redash-host", default=os.getenv("REDASH_HOST", DEFAULT_REDASH_HOST))
    parser.add_argument(
        "--redash-source-ids",
        default=os.getenv(
            "REDASH_SOURCE_IDS",
            ",".join(str(source_id) for source_id in DEFAULT_REDASH_SOURCE_IDS),
        ),
    )
    parser.add_argument(
        "--redash-batch-size",
        type=int,
        default=int(os.getenv("REDASH_BATCH_SIZE", str(DEFAULT_REDASH_BATCH_SIZE))),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = args.redash_api_key or getpass.getpass("Redash API key: ")
    input_path = None if args.use_json_bookings else args.input_path
    booking_ids = read_booking_ids(input_path, args.json)
    source_ids = parse_source_ids(args.redash_source_ids)

    result = fetch_call_comments_for_booking_ids(
        booking_ids=booking_ids,
        api_key=api_key,
        source_ids=source_ids,
        redash_host=args.redash_host,
        batch_size=args.redash_batch_size,
    )
    redash_metadata = {
        "enabled": True,
        "redash_host": args.redash_host,
        "source_id": result.source_id,
        "rows_fetched": len(result.rows),
        "booking_count_with_comments": len(result.comments_by_booking),
    }
    updated, missing = enrich_json(
        json_path=args.json,
        booking_ids=booking_ids,
        comments_by_booking=result.comments_by_booking,
        redash_metadata=redash_metadata,
        dry_run=args.dry_run,
    )

    mode = "Would update" if args.dry_run else "Updated"
    print(f"Booking IDs checked: {len(booking_ids)}")
    print(f"Redash source_id used: {result.source_id}")
    print(f"Rows returned: {len(result.rows)}")
    print(f"Bookings with comments returned: {len(result.comments_by_booking)}")
    print(f"{mode} bookings: {len(updated)}")
    if missing:
        print(f"Bookings without Redash comments or JSON entry: {len(missing)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
