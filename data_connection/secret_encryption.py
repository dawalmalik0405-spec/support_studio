import os

from cryptography.fernet import Fernet


def encrypt_secret(value: str) -> str:
    key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be configured.")
    return Fernet(key.encode("ascii")).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be configured.")
    return Fernet(key.encode("ascii")).decrypt(value.encode("ascii")).decode("utf-8")
