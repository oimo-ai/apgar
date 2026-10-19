from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_SALT = b"apgar-v1"
_CONNECTION_INFO = b"connection-secrets"
_AAD = b"apgar-connection"


class DecryptionError(Exception):
    pass


def generate_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(24)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def token_prefix(plaintext: str) -> str:
    return plaintext[:12]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def derive_key(secret_key: str, info: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=_SALT, info=info).derive(secret_key.encode())


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(token: str) -> bytes:
    padded = token + ("=" * (-len(token) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode())
    except Exception as exc:
        raise DecryptionError("ciphertext is not valid base64url") from exc


class SecretBox:
    def __init__(self, secret_key: str, previous_secret_key: str | None) -> None:
        self._key = derive_key(secret_key, _CONNECTION_INFO)
        self._previous = (
            None
            if previous_secret_key is None
            else derive_key(previous_secret_key, _CONNECTION_INFO)
        )

    def encrypt(self, plaintext: bytes) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext, _AAD)
        return _b64encode(nonce + ciphertext)

    def _decrypt_with(self, key: bytes, token: str) -> bytes:
        raw = _b64decode(token)
        if len(raw) < 12 + 16:
            raise DecryptionError("ciphertext is too short")
        try:
            return AESGCM(key).decrypt(raw[:12], raw[12:], _AAD)
        except InvalidTag as exc:
            raise DecryptionError("ciphertext failed authentication") from exc

    def decrypt(self, token: str) -> bytes:
        try:
            return self._decrypt_with(self._key, token)
        except DecryptionError:
            if self._previous is None:
                raise
        return self._decrypt_with(self._previous, token)

    def needs_reencrypt(self, token: str) -> bool:
        try:
            self._decrypt_with(self._key, token)
        except DecryptionError:
            if self._previous is None:
                raise
            self._decrypt_with(self._previous, token)
            return True
        return False
