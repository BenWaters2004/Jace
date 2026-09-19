# Configuration-aware Jace Core launcher.

import uvicorn

from jace.config import settings


def main() -> None:
    uvicorn.run(
        "jace.main:app",
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
