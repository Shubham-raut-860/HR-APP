from dotenv import load_dotenv

load_dotenv()

import subprocess
import sys

import uvicorn

from app.config import settings


if __name__ == "__main__":
    is_dev = settings.APP_ENV == "development"

    if not is_dev:
        sys.exit(
            subprocess.call(
                [
                    "gunicorn",
                    "--config",
                    "gunicorn.conf.py",
                    "app.main:app",
                ]
            )
        )

    # SQLite cannot handle concurrent writes from multiple workers; force 1.
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    worker_count = 1 if is_sqlite else None

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
        log_level="info",
        workers=worker_count,
    )
