from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from backend.app.domain.tracking_common import (
    COMPLAINT_AGAINST_COLUMN,
    COMPLAINT_AGAINST_ID_COLUMN,
    COMPLAINT_AGAINST_VALUE,
    TITLE_COLUMN,
    TITLE_VALUE,
)


def write_sample_workbook(path: Path) -> None:
    rows = [
        {
            "Booking ID": "B1",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "CARBD - Cab Delay",
            "Loss Amount": 100,
            "Loss Amount (INR)": 100,
            "Recoverable": 100,
            "Recoverable (INR)": 100,
            "Remarks": "Cab Delay - Auto Claim Raised",
            "Approval/Rejected DateTime": "2026-03-19 10:15:00",
        },
        {
            "Booking ID": "B1",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "CARBD - Cab Delay",
            "Loss Amount": 50,
            "Loss Amount (INR)": 50,
            "Recoverable": 50,
            "Recoverable (INR)": 50,
            "Remarks": "Cab Delay",
            "Approval/Rejected DateTime": "2026-03-19 11:15:00",
        },
        {
            "Booking ID": "B2",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "Cancellation",
            "Loss Amount": 20,
            "Loss Amount (INR)": 20,
            "Recoverable": 0,
            "Recoverable (INR)": 0,
            "Remarks": "zero recoverable",
            "Approval/Rejected DateTime": "2026-03-19 12:00:00",
        },
        {
            "Booking ID": "B3",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CD",
            "Sub Category": "Cab Delay",
            "Loss Amount": 20,
            "Loss Amount (INR)": 20,
            "Recoverable": 20,
            "Recoverable (INR)": 20,
            "Remarks": "Cab Delay",
            "Approval/Rejected DateTime": "2026-03-19 12:00:00",
        },
        {
            "Booking ID": "B4",
            "Booking Date": "2026-03-20",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "Cab Delay",
            "Loss Amount": 20,
            "Loss Amount (INR)": 20,
            "Recoverable": 20,
            "Recoverable (INR)": 20,
            "Remarks": "Cab Delay",
            "Approval/Rejected DateTime": "2026-03-20 12:00:00",
        },
    ]
    pd.DataFrame(rows).to_excel(path, index=False)


def write_tracking_json(path: Path) -> None:
    payload = {
        "bookings": {
            "B1": {
                "penalty": {"sub_category": "Cab Delay", "remarks": "Cab Delay"},
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b1",
                        "order_reference_number": "B1",
                        "start_time": "2026-03-19 04:30:00",
                        "driver_started": "2026-03-19 10:20:00",
                        "driver_arrived": "2026-03-19 10:40:00",
                        "boarded": "2026-03-19 10:45:00",
                        "amount": 1200,
                        "base_amount": 1000,
                        "amount_paid": 200,
                        "cash_collected": 1000,
                        "per_km_rate": 20,
                        "total_distance": 50,
                        "extra_travelled": 2,
                        "extra_travelled_fare": 40,
                        "route_toll_charges": 80,
                        "toll_charges": 80,
                        "toll_paid": 1,
                        "parking_charges": 25,
                        "state_tax": 10,
                        "airport_entry_fee": 100,
                        "night_charges": 50,
                        "waiting_charges": "0",
                        "driver_charge_per_day": 150,
                        "total_driver_charge": 150,
                    }
                ],
                "comments": "Customer reported that the cab had not arrived and the driver said they needed 20 minutes.",
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_tracking_json_with_extra_money(path: Path) -> None:
    payload = {
        "bookings": {
            "B1": {
                "penalty": {"sub_category": "Cab Delay", "remarks": "Cab Delay"},
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b1",
                        "order_reference_number": "B1",
                        "start_time": "2026-03-19 04:30:00",
                        "driver_started": "2026-03-19 10:20:00",
                        "driver_arrived": "2026-03-19 10:40:00",
                        "boarded": "2026-03-19 10:45:00",
                    }
                ],
                "comments": "Customer reported cab delay.",
            },
            "B5": {
                "penalty": {"sub_category": "Extra Money Taken", "remarks": "driver collected extra"},
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b5",
                        "order_reference_number": "B5",
                        "type": "ONE_WAY",
                        "ttrip_type": "airport",
                        "amount": 1234,
                        "base_amount": 1000,
                        "amount_paid": 234,
                        "cash_collected": 1000,
                        "per_km_rate": 18.5,
                        "total_distance": 42,
                        "extra_travelled": 5,
                        "extra_travelled_fare": 90,
                        "route_toll_charges": 80,
                        "toll_charges": 80,
                        "toll_paid": 1,
                        "parking_charges": 25,
                        "state_tax": 10,
                        "airport_entry_fee": 200,
                        "night_charges": 50,
                        "waiting_charges": "0",
                        "driver_charge_per_day": 150,
                        "total_driver_charge": 150,
                    }
                ],
                "comments": "Customer said driver collected extra cash for toll and parking.",
            },
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_fulfillment_workbook(path: Path) -> None:
    rows = [
        {
            "Booking ID": "B6",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "FULFILLMENT NOT DONE",
            "Loss Amount": 125,
            "Loss Amount (INR)": 125,
            "Recoverable": 125,
            "Recoverable (INR)": 125,
            "Remarks": "paid amount refund",
            "Approval/Rejected DateTime": "2026-03-19 13:30:00",
        }
    ]
    pd.DataFrame(rows).to_excel(path, index=False)


def write_tracking_json_with_fulfillment(path: Path) -> None:
    payload = {
        "bookings": {
            "B6": {
                "penalty": {"sub_category": "FULFILLMENT NOT DONE", "remarks": "paid amount refund"},
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b6",
                        "order_reference_number": "B6",
                        "booking_status": "CONFIRMED",
                        "tracking_status": "NOT BOARDED",
                        "start_time": "2026-03-18 21:45:00",
                        "driver_started": "2026-03-19 03:21:38.764000",
                        "driver_arrived": "2026-03-19 03:21:44.001000",
                        "amount": 2828,
                        "base_amount": 2413,
                        "amount_paid": 566,
                        "cash_collected": 0,
                        "per_km_rate": 18,
                        "total_distance": 42,
                        "extra_travelled": 0,
                        "extra_travelled_fare": 0,
                        "route_toll_charges": 80,
                        "toll_charges": 80,
                        "toll_paid": 1,
                        "parking_charges": 0,
                        "state_tax": 0,
                        "airport_entry_fee": 200,
                        "night_charges": 0,
                        "waiting_charges": "",
                        "driver_charge_per_day": 0,
                        "total_driver_charge": 0,
                    }
                ],
                "comments": "Customer said the assigned cab did not arrive for the airport pickup.",
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_lower_category_workbook(path: Path) -> None:
    rows = [
        {
            "Booking ID": "B7",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "Lower Category Vehicle",
            "Loss Amount": 200,
            "Loss Amount (INR)": 200,
            "Recoverable": 200,
            "Recoverable (INR)": 200,
            "Remarks": "low category vehicle",
            "Approval/Rejected DateTime": "2026-03-19 14:30:00",
        }
    ]
    pd.DataFrame(rows).to_excel(path, index=False)


def write_tracking_json_with_lower_category(path: Path) -> None:
    payload = {
        "bookings": {
            "B7": {
                "penalty": {"sub_category": "Lower Category Vehicle", "remarks": "low category vehicle"},
                "tracking_reports_raw": [
                    {
                        "dispatch_id": "dispatch-b7",
                        "order_reference_number": "B7",
                        "vehicle_subcategory": "basic-electric",
                        "vehicle_type": "sedan",
                        "amount": 6177,
                        "base_amount": 5712,
                        "amount_paid": 1441,
                        "cash_collected": 4736,
                        "per_km_rate": 40.1,
                        "total_distance": 294,
                        "extra_travelled": 0,
                        "extra_travelled_fare": 0,
                        "route_toll_charges": 0,
                        "toll_charges": 0,
                        "toll_paid": 0,
                        "parking_charges": 0,
                        "state_tax": 0,
                        "airport_entry_fee": 0,
                        "night_charges": 0,
                        "waiting_charges": "0",
                        "driver_charge_per_day": 170,
                        "total_driver_charge": 170,
                    }
                ],
                "comments": "Customer booked an electric sedan but received a CNG hatchback instead.",
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_two_category_workbook(path: Path) -> None:
    rows = [
        {
            "Booking ID": "B1",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "Cab Delay",
            "Loss Amount": 100,
            "Loss Amount (INR)": 100,
            "Recoverable": 100,
            "Recoverable (INR)": 100,
            "Remarks": "Cab Delay",
            "Approval/Rejected DateTime": "2026-03-19 10:15:00",
        },
        {
            "Booking ID": "B5",
            "Booking Date": "2026-03-19",
            "Booking Month": "Mar 2026",
            "Loss Dept": "CARBD",
            "Sub Category": "Extra Money Taken",
            "Loss Amount": 80,
            "Loss Amount (INR)": 80,
            "Recoverable": 80,
            "Recoverable (INR)": 80,
            "Remarks": "driver collected extra",
            "Approval/Rejected DateTime": "2026-03-19 10:30:00",
        },
    ]
    pd.DataFrame(rows).to_excel(path, index=False)


def mock_llm(prompt: str, _tokens: int, _effort: str) -> str:
    if "Agent specialist decision task." in prompt or "Judge Agent verification task." in prompt:
        return build_agent_decision_response(prompt)
    if "Portfolio Summary Agent task." in prompt:
        return json.dumps(
            {
                "executive_summary": "LLM portfolio summary: recovery cases were investigated and routed by confidence.",
                "top_complaint_drivers": ["Cab Delay: high recoverable exposure"],
                "recommended_actions": ["Prioritize high-confidence recoveries and review evidence gaps."],
                "missing_data_hotspots": [],
                "category_breakdown": [],
            }
        )
    if "Complaint category classification task." in prompt:
        if "extra cash" in prompt or "Sub Category: Extra Money Taken" in prompt:
            return '{"categories": ["Extra Money Taken"]}'
        if "Lower Category Vehicle" in prompt or "electric sedan" in prompt:
            return '{"categories": ["Low Category Vehicle"]}'
        if "FULFILLMENT NOT DONE" in prompt or "did not arrive" in prompt:
            return '{"categories": ["Vendor No Show"]}'
        if "Driver Behavior" in prompt or "driver behaved rudely" in prompt:
            return '{"categories": ["Bad Driver Behaviour/Skill"]}'
        if "Sub Category: AC not working" in prompt:
            return '{"categories": ["AC Not Working"]}'
        if "Sub Category: Vehicle Breakdown" in prompt:
            return '{"categories": ["Cab Breakdown"]}'
        return '{"categories": ["Cab Delay"]}'
    if "customer_booked_vehicle" in prompt:
        return '{"customer_booked_vehicle": "electric sedan", "customer_received_vehicle": "CNG hatchback"}'
    if "Customer call comment:" in prompt:
        return "Mock combined summary."
    return "Mock Incabs insight."


def build_agent_decision_response(prompt: str) -> str:
    sub_category = regex_value(prompt, r'"sub_category":\s*"([^"]+)"')
    evidence_ids = list(dict.fromkeys(re.findall(r'"id":\s*"([^"]+)"', prompt)))[:3]
    amount = float(regex_value(prompt, r'"recoverable_amount":\s*([0-9.]+)') or 100)
    category = agent_category_for_subcategory(sub_category, prompt)
    status = "auto_ready" if evidence_ids else "missing_evidence"
    return json.dumps(
        {
            "decision": "valid_penalty" if status == "auto_ready" else "needs_review",
            "complaint_categories": [category],
            "confidence": 0.91 if status == "auto_ready" else 0.55,
            "recommended_recovery_amount": amount if status == "auto_ready" else 0,
            "rationale": f"Mock LLM found {category} supported by cited evidence.",
            "recommended_action": "Ready for Cab Ops recovery package" if status == "auto_ready" else "Review manually",
            "review_status": status,
            "review_reason": "Mock LLM judge approved the cited evidence." if status == "auto_ready" else "Evidence is incomplete.",
            "evidence_ids": evidence_ids,
        }
    )


def agent_category_for_subcategory(sub_category: str, prompt: str) -> str:
    normalized = sub_category.casefold()
    if "extra money" in normalized:
        return "Extra Money Taken"
    if "fulfillment" in normalized or "fulfilment" in normalized:
        return "Vendor No Show"
    if "lower category" in normalized:
        return "Low Category Vehicle"
    if "driver behavior" in normalized or "driver behaviour" in normalized:
        return "Bad Driver Behaviour/Skill"
    if "ac not working" in normalized:
        return "AC Not Working"
    if "vehicle breakdown" in normalized:
        return "Cab Breakdown"
    if "Cab Delayed > 15 Minutes" in prompt:
        return "Cab Delayed > 15 Minutes"
    return "Cab Delay"


def regex_value(value: str, pattern: str) -> str:
    match = re.search(pattern, value)
    return match.group(1) if match else ""


def assert_complaint_metadata(row: pd.Series | dict[str, object], dispatch_id: str) -> None:
    assert row[COMPLAINT_AGAINST_COLUMN] == COMPLAINT_AGAINST_VALUE
    assert row[COMPLAINT_AGAINST_ID_COLUMN] == dispatch_id
    assert row[TITLE_COLUMN] == TITLE_VALUE
