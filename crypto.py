"""
crypto.py — Optional Fernet symmetric encryption for sensitive configuration and credentials.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTO_AVAILABLE = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    CRYPTO_AVAILABLE = False

_fernet_instance: Optional[Fernet] = None
_key_source: str = "none"


def init_crypto(key_from_db: Optional[str] = None) -> Optional[str]:
    """
    Initialize Fernet instance from env var ENCRYPTION_KEY, DB stored key,
    or generate a new stable key. Returns the key string (for saving to DB if newly generated).
    """
    global _fernet_instance, _key_source
    if not CRYPTO_AVAILABLE:
        logger.warning("[crypto] cryptography library not installed — running without encryption.")
        return None

    env_key = os.getenv("ENCRYPTION_KEY", "").strip()
    target_key: str = ""

    if env_key:
        target_key = env_key
        _key_source = "env"
    elif key_from_db:
        target_key = key_from_db
        _key_source = "database"
    else:
        target_key = Fernet.generate_key().decode()
        _key_source = "generated"

    try:
        # Validate that the key works
        _fernet_instance = Fernet(target_key.encode() if isinstance(target_key, str) else target_key)
        logger.info("[crypto] Fernet encryption active (source: %s)", _key_source)
        return target_key
    except Exception as e:
        logger.error("[crypto] Invalid Fernet key (%s): %s", _key_source, e)
        _fernet_instance = None
        _key_source = "error"
        return None


def is_crypto_active() -> bool:
    return _fernet_instance is not None


def get_crypto_status() -> dict:
    return {
        "available": CRYPTO_AVAILABLE,
        "active": is_crypto_active(),
        "source": _key_source,
    }


def encrypt(plaintext: str) -> str:
    """Encrypt a string. If crypto is not active or text already encrypted, return as is."""
    if not plaintext or not isinstance(plaintext, str):
        return plaintext
    if plaintext.startswith("ENC:"):
        return plaintext
    if not _fernet_instance:
        return plaintext
    try:
        token = _fernet_instance.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return f"ENC:{token}"
    except Exception as e:
        logger.error("[crypto] Encryption error: %s", e)
        return plaintext


def decrypt(ciphertext: str) -> str:
    """Decrypt an ENC:... string. If not encrypted or crypto not active, return as is."""
    if not ciphertext or not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext.startswith("ENC:"):
        return ciphertext
    if not _fernet_instance:
        logger.warning("[crypto] Cannot decrypt 'ENC:...' — Fernet instance not initialized.")
        return ciphertext
    token = ciphertext[4:]
    try:
        return _fernet_instance.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("[crypto] Decryption failed: invalid token / mismatched key.")
        return ciphertext
    except Exception as e:
        logger.error("[crypto] Decryption error: %s", e)
        return ciphertext
