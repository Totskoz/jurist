"""`python -m jurist.api` — launches uvicorn with the FastAPI app."""
from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "jurist.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
