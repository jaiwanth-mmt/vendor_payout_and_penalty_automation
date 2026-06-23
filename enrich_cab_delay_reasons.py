from __future__ import annotations

from backend.app.domain.cab_delay_enrichment import *  # noqa: F403
from backend.app.cli.enrich_cab_delay_reasons import main


if __name__ == "__main__":
    raise SystemExit(main())
