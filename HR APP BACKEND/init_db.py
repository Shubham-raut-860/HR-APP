import asyncio
import sys
import os

# Add the current directory to sys.path to find the 'app' package
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.database import create_tables

if __name__ == "__main__":
    print("Initializing database tables...")
    asyncio.run(create_tables())
    print("Database initialization complete.")
