from app.config import settings
import json

def check_config():
    print("CORS_ORIGINS (raw):", settings.CORS_ORIGINS)
    print("cors_origins_list:", settings.cors_origins_list)
    print("DATABASE_URL:", settings.DATABASE_URL)
    print("APP_ENV:", settings.APP_ENV)

if __name__ == "__main__":
    check_config()
