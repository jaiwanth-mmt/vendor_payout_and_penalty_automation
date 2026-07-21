from __future__ import annotations


def main() -> None:
    print("Agentic Loss Recovery Copilot")
    print()
    print("API server:")
    print("  uv run uvicorn backend.app.main:app --reload")
    print()
    print("Frontend:")
    print("  cd frontend && npm run dev")
    print()
    print("Tests:")
    print("  uv run pytest")
    print("  cd frontend && npm run build")
    print()
    print("Tracking data is fetched live from MySQL + Redash during each job.")
    print("data/demo/tracking_reports_by_booking.json is reference-only.")


if __name__ == "__main__":
    main()
