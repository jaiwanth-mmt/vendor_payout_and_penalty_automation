from __future__ import annotations


def main() -> None:
    print("Penalty Automation project")
    print("Backend API: uv run uvicorn backend.app.main:app --reload")
    print("Frontend: cd frontend && npm run dev")
    print("Tests: uv run pytest && cd frontend && npm run build")


if __name__ == "__main__":
    main()

