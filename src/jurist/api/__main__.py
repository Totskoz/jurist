"""`python -m jurist.api` — launches uvicorn with the FastAPI app."""
from __future__ import annotations

import logging

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    uvicorn.run(
        "jurist.api.app:app",
        host="127.0.0.1",
        port=8766,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
