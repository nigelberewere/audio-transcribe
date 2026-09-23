import base64
import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        raw = base64.b64decode(encoded.encode())
        return hmac.compare_digest(hash_password_with_salt(password, raw[:16]), raw[16:])
    except (ValueError, TypeError):
        return False


def hash_password_with_salt(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
