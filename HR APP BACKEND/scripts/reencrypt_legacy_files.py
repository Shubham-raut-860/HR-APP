"""
One-off utility: re-encrypt stored resume files with the current primary key.

Use this after key rotation to migrate legacy plaintext or old-key ciphertext
to the active key material. Not used by request-time code paths.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import StoredResume
from app.services import encryption_service


async def _reencrypt_all(*, dry_run: bool) -> None:
    migrated = 0
    skipped_missing = 0
    failed = 0

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(StoredResume.id, StoredResume.resume_path))).all()

    for resume_id, resume_path in rows:
        if not resume_path:
            continue
        path = Path(resume_path)
        if not path.exists():
            skipped_missing += 1
            continue

        try:
            plaintext = encryption_service.decrypt_file_from_path(str(path))
            if dry_run:
                migrated += 1
                continue

            with tempfile.NamedTemporaryFile(delete=False, suffix=path.suffix) as temp_fp:
                temp_path = temp_fp.name
            try:
                encryption_service.encrypt_file_to_path(plaintext, temp_path)
                os.replace(temp_path, str(path))
                migrated += 1
            finally:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
        except Exception as exc:
            failed += 1
            print(f"[FAILED] stored_resume_id={resume_id} path={path} error={exc}")

    print(
        f"Completed. migrated={migrated} skipped_missing={skipped_missing} failed={failed} dry_run={dry_run}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-encrypt stored resumes with active primary key")
    parser.add_argument("--dry-run", action="store_true", help="Validate decryptability without rewriting files")
    args = parser.parse_args()
    asyncio.run(_reencrypt_all(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()
