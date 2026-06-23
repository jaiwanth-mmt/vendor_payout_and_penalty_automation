from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import httpx


DEFAULT_REDASH_HOST = "http://common-redash.mmt.com"
DEFAULT_REDASH_SOURCE_IDS = (10,)
DEFAULT_REDASH_BATCH_SIZE = 250


@dataclass(frozen=True)
class RedashCommentResult:
    source_id: int
    rows: list[dict[str, Any]]
    comments_by_booking: dict[str, str]


def parse_source_ids(value: str) -> tuple[int, ...]:
    source_ids = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not source_ids:
        raise ValueError("At least one Redash source ID is required.")
    return source_ids


def unique_booking_ids(booking_ids: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in booking_ids:
        booking_id = str(value or "").strip()
        if not booking_id or booking_id in seen:
            continue
        seen.add(booking_id)
        output.append(booking_id)
    return output


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def chunked(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def build_call_comments_query(booking_ids: list[str]) -> str:
    booking_id_sql = ", ".join(sql_string(booking_id) for booking_id in booking_ids)
    return f"""
WITH base AS (
    SELECT
        td.entitykeyvirtual AS booking_id,
        a.ticketid AS task_id,
        a.frustrationscore,
        a.summary AS comments,
        td.comments AS remarks
    FROM vortex.callattributes a
    LEFT JOIN vortex.calldetails b
        ON a.ticketid = b.ticketid
    INNER JOIN ticketdetails td
        ON td.clientinteractionid = a.ucid
    WHERE b.calltype = 'INBOUND'
      AND td.channel = 1
      AND td.entitykeyvirtual IN ({booking_id_sql})
),

ranked AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY task_id
               ORDER BY LENGTH(COALESCE(comments, '')) DESC
           ) AS rn
    FROM base
)

SELECT
    booking_id,
    task_id,
    frustrationscore,
    comments,
    remarks
FROM ranked
WHERE rn = 1;
""".strip()


def redash_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }


def fetch_redash_rows(
    *,
    query_text: str,
    source_id: int,
    api_key: str,
    redash_host: str = DEFAULT_REDASH_HOST,
) -> list[dict[str, Any]]:
    redash_host = redash_host.rstrip("/")
    headers = redash_headers(api_key)
    payload = {"data_source_id": source_id, "query": query_text}

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        response = client.post(f"{redash_host}/api/query_results", headers=headers, json=payload)
        response.raise_for_status()
        response_json = response.json()

        if "query_result" in response_json:
            result_data = response_json
        elif "job" in response_json:
            result_data = wait_for_redash_job(
                client=client,
                redash_host=redash_host,
                headers=headers,
                job_id=response_json["job"]["id"],
            )
        else:
            raise KeyError(f"Unexpected Redash response keys: {sorted(response_json)}")

    return result_data["query_result"]["data"]["rows"]


def wait_for_redash_job(
    *,
    client: httpx.Client,
    redash_host: str,
    headers: dict[str, str],
    job_id: str,
) -> dict[str, Any]:
    while True:
        job_response = client.get(f"{redash_host}/api/jobs/{job_id}", headers=headers)
        job_response.raise_for_status()
        job_data = job_response.json()
        job = job_data["job"]
        job_status = job["status"]

        if job_status == 3:
            result_url = f"{redash_host}/api/query_results/{job['query_result_id']}.json"
            result_response = client.get(result_url, headers=headers)
            result_response.raise_for_status()
            return result_response.json()

        if job_status == 4:
            raise RuntimeError(f"Query failed: {job.get('error')}")

        time.sleep(2)


def fetch_rows_from_first_working_source(
    *,
    query_text: str,
    source_ids: tuple[int, ...],
    api_key: str,
    redash_host: str,
) -> tuple[int, list[dict[str, Any]]]:
    errors: list[str] = []
    for source_id in source_ids:
        try:
            rows = fetch_redash_rows(
                query_text=query_text,
                source_id=source_id,
                api_key=api_key,
                redash_host=redash_host,
            )
            return source_id, rows
        except Exception as error:
            errors.append(f"source_id={source_id}: {error}")

    raise RuntimeError("Redash query failed for all source IDs:\n" + "\n".join(errors))


def coerce_comment(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_comments_by_booking(rows: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        booking_id = str(row.get("booking_id") or "").strip()
        comment = coerce_comment(row.get("comments"))
        if not booking_id or not comment:
            continue
        if comment not in grouped[booking_id]:
            grouped[booking_id].append(comment)

    return {
        booking_id: "\n\n".join(sorted(comments, key=len, reverse=True))
        for booking_id, comments in grouped.items()
    }


def fetch_call_comments_for_booking_ids(
    booking_ids: Iterable[Any],
    *,
    api_key: str,
    source_ids: tuple[int, ...] = DEFAULT_REDASH_SOURCE_IDS,
    redash_host: str = DEFAULT_REDASH_HOST,
    batch_size: int = DEFAULT_REDASH_BATCH_SIZE,
) -> RedashCommentResult:
    if not source_ids:
        raise ValueError("At least one Redash source ID is required.")
    if batch_size <= 0:
        raise ValueError("Redash batch size must be greater than zero.")

    unique_ids = unique_booking_ids(booking_ids)
    if not unique_ids:
        return RedashCommentResult(source_id=source_ids[0], rows=[], comments_by_booking={})

    all_rows: list[dict[str, Any]] = []
    active_source_id: int | None = None

    for booking_id_batch in chunked(unique_ids, batch_size):
        query_text = build_call_comments_query(booking_id_batch)
        if active_source_id is None:
            active_source_id, rows = fetch_rows_from_first_working_source(
                query_text=query_text,
                source_ids=source_ids,
                api_key=api_key,
                redash_host=redash_host,
            )
        else:
            rows = fetch_redash_rows(
                query_text=query_text,
                source_id=active_source_id,
                api_key=api_key,
                redash_host=redash_host,
            )
        all_rows.extend(rows)

    if active_source_id is None:
        active_source_id = source_ids[0]

    return RedashCommentResult(
        source_id=active_source_id,
        rows=all_rows,
        comments_by_booking=build_comments_by_booking(all_rows),
    )
