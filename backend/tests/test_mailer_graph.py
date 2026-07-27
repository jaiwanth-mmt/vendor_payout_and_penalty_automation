from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest

from backend.app.agents.mailer.graphs import MAILER_NODE_NAMES, build_mailer_graph, mailer_topology_payload
from backend.app.agents.mailer.runner import run_mailer_graph
from backend.app.integrations.smtp import InMemoryMailTransport
from backend.app.services.mailer import preview_vendor_mails, save_dispatch, send_vendor_mails
from backend.app.services.package_builder import FINAL_EXPORT_COLUMNS, PROCESSED_CATEGORY_ROOT, write_workbook


def test_mailer_graph_compiles_and_exposes_nodes() -> None:
    graph = build_mailer_graph()
    topology = mailer_topology_payload()
    assert topology["nodes"] == MAILER_NODE_NAMES
    assert "assign" in topology["mermaid"]
    assert graph is not None


def test_mailer_preview_is_deterministic_for_same_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILER_RECIPIENTS", "one@go-mmt.com,two@go-mmt.com,three@go-mmt.com")
    job_dir = tmp_path / "job"
    processed = job_dir / PROCESSED_CATEGORY_ROOT
    processed.mkdir(parents=True)
    final_path = job_dir / "final_output.xlsx"
    rows = [
        {
            "booking_id": "B1",
            "complaint_reasons": "Cab Delay",
            "complaint_against": "dispatch_id",
            "complaint_against_id": "D1",
            "title": "Service Issue",
            "message": "Delayed pickup",
            "fine": 100,
        },
        {
            "booking_id": "B2",
            "complaint_reasons": "Cab Delay",
            "complaint_against": "dispatch_id",
            "complaint_against_id": "D2",
            "title": "Service Issue",
            "message": "Late arrival",
            "fine": 200,
        },
        {
            "booking_id": "B3",
            "complaint_reasons": "Vendor No Show",
            "complaint_against": "dispatch_id",
            "complaint_against_id": "D3",
            "title": "Service Issue",
            "message": "No show",
            "fine": 300,
        },
    ]
    write_workbook(pd.DataFrame(rows, columns=FINAL_EXPORT_COLUMNS), final_path)
    write_workbook(
        pd.DataFrame(
            [
                {"Booking ID": "B1", "comments": "caller said late"},
                {"Booking ID": "B2", "comments": ""},
                {"Booking ID": "B3", "comments": "confirmed no show"},
            ]
        ),
        processed / "cab_delay.xlsx",
    )

    first = asyncio.run(preview_vendor_mails(job_id="job1", job_dir=job_dir, final_output_path=final_path))
    second = asyncio.run(preview_vendor_mails(job_id="job1", job_dir=job_dir, final_output_path=final_path))
    assert first["preview_token"] == second["preview_token"]
    assert first["assignments"] == second["assignments"]
    assert len(first["drafts"]) == 3
    transcript_draft = next(item for item in first["drafts"] if item["booking_id"] == "B1")
    assert "call transcript" in transcript_draft["text_body"]
    no_transcript = next(item for item in first["drafts"] if item["booking_id"] == "B2")
    assert "call transcript" not in no_transcript["text_body"]


def test_mailer_send_once_and_blocks_resend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILER_RECIPIENTS", "one@go-mmt.com,two@go-mmt.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    final_path = job_dir / "final_output.xlsx"
    write_workbook(
        pd.DataFrame(
            [
                {
                    "booking_id": "B1",
                    "complaint_reasons": "Cab Delay",
                    "complaint_against": "dispatch_id",
                    "complaint_against_id": "D1",
                    "title": "Service Issue",
                    "message": "Delayed",
                    "fine": 50,
                },
                {
                    "booking_id": "B2",
                    "complaint_reasons": "Cab Delay",
                    "complaint_against": "dispatch_id",
                    "complaint_against_id": "D2",
                    "title": "Service Issue",
                    "message": "Late",
                    "fine": 75,
                },
            ],
            columns=FINAL_EXPORT_COLUMNS,
        ),
        final_path,
    )
    transport = InMemoryMailTransport()
    preview = asyncio.run(preview_vendor_mails(job_id="job2", job_dir=job_dir, final_output_path=final_path))
    sent = asyncio.run(
        send_vendor_mails(
            job_id="job2",
            job_dir=job_dir,
            final_output_path=final_path,
            preview_token=str(preview["preview_token"]),
            transport=transport,
        )
    )
    assert sent["status"] == "sent"
    assert len(transport.sent) == 2
    with pytest.raises(ValueError, match="already sent"):
        asyncio.run(
            send_vendor_mails(
                job_id="job2",
                job_dir=job_dir,
                final_output_path=final_path,
                preview_token=str(preview["preview_token"]),
                transport=transport,
            )
        )


def test_mailer_graph_send_mode_records_failures() -> None:
    transport = InMemoryMailTransport(fail_for={"bad@go-mmt.com"})
    result = asyncio.run(
        run_mailer_graph(
            job_id="job3",
            mode="send",
            preview_token="tok",
            final_output_checksum="abc",
            recipients=["good@go-mmt.com", "bad@go-mmt.com"],
            booking_rows=[
                {"booking_id": "B1", "title": "Service Issue", "message": "m1", "fine": 1, "call_transcript": ""},
                {"booking_id": "B2", "title": "Service Issue", "message": "m2", "fine": 2, "call_transcript": ""},
            ],
            transport=transport,
        )
    )
    assert result["status"] == "partial"
    assert len(transport.sent) == 1
    assert {item["status"] for item in result["results"]} == {"sent", "failed"}


def test_stale_preview_token_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILER_RECIPIENTS", "one@go-mmt.com")
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    final_path = job_dir / "final_output.xlsx"
    write_workbook(
        pd.DataFrame(
            [
                {
                    "booking_id": "B1",
                    "complaint_reasons": "Cab Delay",
                    "complaint_against": "dispatch_id",
                    "complaint_against_id": "D1",
                    "title": "Service Issue",
                    "message": "Delayed",
                    "fine": 50,
                }
            ],
            columns=FINAL_EXPORT_COLUMNS,
        ),
        final_path,
    )
    preview = asyncio.run(preview_vendor_mails(job_id="job4", job_dir=job_dir, final_output_path=final_path))
    save_dispatch(
        job_dir,
        {
            **preview,
            "status": "preview_ready",
            "preview_token": preview["preview_token"],
            "drafts": preview["drafts"],
            "final_output_checksum": preview["final_output_checksum"],
            "recipients": preview["recipients"],
        },
    )
    with pytest.raises(ValueError, match="preview_token"):
        asyncio.run(
            send_vendor_mails(
                job_id="job4",
                job_dir=job_dir,
                final_output_path=final_path,
                preview_token="wrong-token",
                transport=InMemoryMailTransport(),
            )
        )
