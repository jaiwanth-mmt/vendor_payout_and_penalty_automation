# Demo / reference data

- `qliksense_dump.xlsx` — sample QlikSense workbook for local UI demos and optional manual runs.
- `tracking_reports_by_booking.json` — **reference only**. Shows the shape of live tracking payloads (`bookings[booking_id].tracking_reports_raw`, `comments`, `vendor_name` on rows). The API does **not** read this file; jobs fetch MySQL `tracking_reports_raw`, join `incabs_suppliers`, and optionally Redash comments for Booking IDs in the selected approval-date range.
- `expected_agentic_loss_recovery_output.xlsx` — historical expected output shape for reference.
