
from dotenv import load_dotenv
load_dotenv()

import uvicorn
from app.config import settings

if __name__ == "__main__":
    # SQLite cannot handle concurrent writes from multiple workers — force 1.
    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    is_dev = settings.APP_ENV == "development"
    
    # uvicorn >= 0.20: reload and workers are mutually exclusive.
    worker_count = None if is_dev else (1 if is_sqlite else 4)
    
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=is_dev,
        log_level="info",
        workers=worker_count,
    )
