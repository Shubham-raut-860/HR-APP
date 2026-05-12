"""
Encryption service – protects PII and raw resume files at rest
Uses symmetric encryption (Fernet) based on the app's ENCRYPTION_KEY.
"""
import base64
import hashlib
import logging
import os
import struct
from functools import lru_cache
from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import settings

logger = logging.getLogger(__name__)

# Static salt embedded in the application. This is NOT a secret — its purpose
# is purely domain-separation so that keys derived from the same passphrase
# cannot be reused across different applications. The passphrase (ENCRYPTION_KEY)
# remains secret. For higher security, store a per-deployment salt in a secrets
# manager and load it alongside the passphrase.
_SALT = b"hr_platform_fernet_v1"
_FILE_SALT = b"hr_platform_file_aesgcm_v1"
_FILE_MAGIC = b"HRAPPA2\x00"
_FILE_VERSION = 1
_FILE_CHUNK_SIZE = 64 * 1024


# FIX (Bug #1 - CRITICAL PERFORMANCE): _get_cipher() previously ran 390,000
# PBKDF2-SHA256 iterations on EVERY encrypt/decrypt call — meaning every file
# save, resume read, and text encryption was needlessly expensive.
# @lru_cache(maxsize=4) memoises on the key string so the derivation only runs
# once per unique key value for the lifetime of the process.
# SECURITY TRADE-OFF: @lru_cache stores derived Fernet key objects in an
# in-memory dict for the lifetime of the process.  If an attacker obtains a
# memory dump (core dump, /proc/pid/mem), the derived 256-bit keys are
# directly recoverable from the cache.  The alternative — re-deriving via
# 390k PBKDF2 iterations on every call — adds ~100ms per encrypt/decrypt.
# For high-security deployments, replace this with an HSM-backed KMS (e.g.
# AWS KMS, Azure Key Vault, HashiCorp Vault Transit) that never exposes
# key material to the application process at all.
@lru_cache(maxsize=4)
def _derive_fernet(key: str) -> Fernet:
    """Derive and cache a Fernet instance from the given passphrase string.

    PBKDF2-HMAC-SHA256 with 390,000 iterations (OWASP 2023 recommendation).
    Cached via @lru_cache so the expensive derivation runs exactly once per
    unique passphrase per process lifetime.
    """
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        key.encode("utf-8"),
        _SALT,
        iterations=600_000,
        dklen=32,
    )
    fernet_key = base64.urlsafe_b64encode(raw)
    return Fernet(fernet_key)


@lru_cache(maxsize=4)
def _derive_file_key(key: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        key.encode("utf-8"),
        _FILE_SALT,
        iterations=600_000,
        dklen=32,
    )


def _get_cipher() -> MultiFernet:
    key_env = settings.ENCRYPTION_KEY
    if not key_env or len(key_env) < 32:
        # FIX Finding 28: Remove insecure fallback key and enforce configuration
        raise RuntimeError(
            "CRITICAL: ENCRYPTION_KEY environment variable is missing or too short. "
            "Must be at least 32 characters."
        )
    
    # FIX: Implement Key Rotation support using MultiFernet.
    # ENCRYPTION_KEY can now be a comma-separated list of keys (e.g. "NEW_KEY,OLD_KEY").
    # The first key is used for all new encryption; all keys are tried for decryption.
    raw_keys = [k.strip() for k in key_env.split(",")]
    keys: list[str] = []
    for idx, k in enumerate(raw_keys, start=1):
        if len(k) >= 32:
            keys.append(k)
        else:
            # Warn loudly so a truncated rotation key doesn't silently make
            # old ciphertext undecryptable with zero diagnostic output.
            logger.warning(
                "ENCRYPTION_KEY entry #%d dropped: only %d chars (need >= 32). "
                "Data encrypted with this key will be undecryptable.",
                idx, len(k),
            )
    if not keys:
         raise RuntimeError("No valid 32+ char keys found in ENCRYPTION_KEY.")

    return MultiFernet([_derive_fernet(k) for k in keys])


def _get_file_keys() -> list[bytes]:
    key_env = settings.ENCRYPTION_KEY
    if not key_env or len(key_env) < 32:
        raise RuntimeError(
            "CRITICAL: ENCRYPTION_KEY environment variable is missing or too short. "
            "Must be at least 32 characters."
        )
    keys = [k.strip() for k in key_env.split(",") if len(k.strip()) >= 32]
    if not keys:
        raise RuntimeError("No valid 32+ char keys found in ENCRYPTION_KEY.")
    return [_derive_file_key(k) for k in keys]


def _is_chunked_file_ciphertext(content: bytes) -> bool:
    return len(content) > len(_FILE_MAGIC) and content.startswith(_FILE_MAGIC)


def _decrypt_chunked_file_content(content: bytes) -> bytes:
    if len(content) < len(_FILE_MAGIC) + 1 + 8 + 4:
        raise DecryptionError("Chunked encrypted file is truncated")

    off = 0
    if content[:len(_FILE_MAGIC)] != _FILE_MAGIC:
        raise DecryptionError("Chunked encrypted file has invalid header")
    off += len(_FILE_MAGIC)
    version = content[off]
    off += 1
    if version != _FILE_VERSION:
        raise DecryptionError(f"Unsupported encrypted file version: {version}")
    nonce_prefix = content[off:off + 8]
    off += 8
    chunk_size = struct.unpack(">I", content[off:off + 4])[0]
    off += 4
    if chunk_size <= 0:
        raise DecryptionError("Invalid encrypted file chunk size")

    for key in _get_file_keys():
        aesgcm = AESGCM(key)
        counter = 0
        cursor = off
        plain = bytearray()
        try:
            while cursor < len(content):
                if cursor + 4 > len(content):
                    raise DecryptionError("Chunk length header is truncated")
                clen = struct.unpack(">I", content[cursor:cursor + 4])[0]
                cursor += 4
                if clen <= 16:
                    raise DecryptionError("Encrypted chunk is too short")
                if cursor + clen > len(content):
                    raise DecryptionError("Encrypted chunk payload is truncated")
                enc_chunk = content[cursor:cursor + clen]
                cursor += clen
                nonce = nonce_prefix + counter.to_bytes(4, "big")
                aad = counter.to_bytes(4, "big")
                plain.extend(aesgcm.decrypt(nonce, enc_chunk, aad))
                counter += 1
            return bytes(plain)
        except Exception:
            continue
    raise DecryptionError("File decryption failed: key mismatch or data corruption")


def _decrypt_chunked_file_stream(fh) -> bytes:
    magic = fh.read(len(_FILE_MAGIC))
    if magic != _FILE_MAGIC:
        raise DecryptionError("Chunked encrypted file has invalid header")

    version_raw = fh.read(1)
    if len(version_raw) != 1:
        raise DecryptionError("Chunked encrypted file header is truncated")
    version = version_raw[0]
    if version != _FILE_VERSION:
        raise DecryptionError(f"Unsupported encrypted file version: {version}")

    nonce_prefix = fh.read(8)
    if len(nonce_prefix) != 8:
        raise DecryptionError("Chunked encrypted file nonce prefix is truncated")

    chunk_size_raw = fh.read(4)
    if len(chunk_size_raw) != 4:
        raise DecryptionError("Chunked encrypted file chunk size is truncated")
    chunk_size = struct.unpack(">I", chunk_size_raw)[0]
    if chunk_size <= 0:
        raise DecryptionError("Invalid encrypted file chunk size")

    for key in _get_file_keys():
        aesgcm = AESGCM(key)
        plain = bytearray()
        counter = 0
        fh.seek(len(_FILE_MAGIC) + 1 + 8 + 4)
        try:
            while True:
                len_raw = fh.read(4)
                if not len_raw:
                    return bytes(plain)
                if len(len_raw) != 4:
                    raise DecryptionError("Chunk length header is truncated")
                clen = struct.unpack(">I", len_raw)[0]
                if clen <= 16:
                    raise DecryptionError("Encrypted chunk is too short")
                enc_chunk = fh.read(clen)
                if len(enc_chunk) != clen:
                    raise DecryptionError("Encrypted chunk payload is truncated")
                nonce = nonce_prefix + counter.to_bytes(4, "big")
                aad = counter.to_bytes(4, "big")
                plain.extend(aesgcm.decrypt(nonce, enc_chunk, aad))
                counter += 1
        except Exception:
            continue
    raise DecryptionError("File decryption failed: key mismatch or data corruption")


def encrypt_text(plain_text: str) -> str:
    if not plain_text:
        return plain_text
    return _get_cipher().encrypt(plain_text.encode("utf-8")).decode("utf-8")


class DecryptionError(RuntimeError):
    """Raised when Fernet decryption fails - key mismatch or data corruption."""


def decrypt_text(encrypted_text: str) -> str:
    if not encrypted_text:
        return encrypted_text
    try:
        return _get_cipher().decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "decrypt_text failed - possible key mismatch or data corruption: %s", exc
        )
        raise DecryptionError(f"Text decryption failed: {exc}") from exc


def encrypt_file(file_content: bytes) -> bytes:
    # Backward compatible return type for call-sites that expect in-memory bytes.
    # Uses chunked AES-GCM payload format to reduce overhead and allow streamed writes.
    keys = _get_file_keys()
    aesgcm = AESGCM(keys[0])
    nonce_prefix = os.urandom(8)

    out = bytearray()
    out.extend(_FILE_MAGIC)
    out.append(_FILE_VERSION)
    out.extend(nonce_prefix)
    out.extend(struct.pack(">I", _FILE_CHUNK_SIZE))

    counter = 0
    for start in range(0, len(file_content), _FILE_CHUNK_SIZE):
        chunk = file_content[start:start + _FILE_CHUNK_SIZE]
        nonce = nonce_prefix + counter.to_bytes(4, "big")
        aad = counter.to_bytes(4, "big")
        enc_chunk = aesgcm.encrypt(nonce, chunk, aad)
        out.extend(struct.pack(">I", len(enc_chunk)))
        out.extend(enc_chunk)
        counter += 1
    return bytes(out)


def encrypt_file_to_path(file_content: bytes, destination_path: str) -> None:
    """
    Stream encrypted chunks directly to disk to avoid creating a second full-size
    encrypted buffer in memory.
    """
    keys = _get_file_keys()
    aesgcm = AESGCM(keys[0])
    nonce_prefix = os.urandom(8)

    with open(destination_path, "wb") as fh:
        fh.write(_FILE_MAGIC)
        fh.write(bytes([_FILE_VERSION]))
        fh.write(nonce_prefix)
        fh.write(struct.pack(">I", _FILE_CHUNK_SIZE))

        counter = 0
        for start in range(0, len(file_content), _FILE_CHUNK_SIZE):
            chunk = file_content[start:start + _FILE_CHUNK_SIZE]
            nonce = nonce_prefix + counter.to_bytes(4, "big")
            aad = counter.to_bytes(4, "big")
            enc_chunk = aesgcm.encrypt(nonce, chunk, aad)
            fh.write(struct.pack(">I", len(enc_chunk)))
            fh.write(enc_chunk)
            counter += 1


def decrypt_file(encrypted_content: bytes) -> bytes:
    try:
        if _is_chunked_file_ciphertext(encrypted_content):
            return _decrypt_chunked_file_content(encrypted_content)
        return _get_cipher().decrypt(encrypted_content)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "decrypt_file failed - possible key mismatch or data corruption: %s", exc
        )
        raise DecryptionError(f"File decryption failed: {exc}") from exc


def decrypt_file_from_path(source_path: str) -> bytes:
    with open(source_path, "rb") as fh:
        header = fh.read(len(_FILE_MAGIC))
        fh.seek(0)
        if header == _FILE_MAGIC:
            return _decrypt_chunked_file_stream(fh)
        return decrypt_file(fh.read())


def try_decrypt_file(encrypted_content: bytes) -> bytes | None:
    """
    Best-effort file decrypt without error logging.
    Use when probing whether bytes are encrypted-at-rest artifacts
    (e.g., accidental re-upload of files from uploads/resumes).
    """
    try:
        if _is_chunked_file_ciphertext(encrypted_content):
            return _decrypt_chunked_file_content(encrypted_content)
        return _get_cipher().decrypt(encrypted_content)
    except Exception:
        return None
