from __future__ import annotations

import base64
import hashlib

import pytest

from apgar.security import (
    DecryptionError,
    SecretBox,
    derive_key,
    generate_token,
    hash_token,
    hmac_sha256,
    token_prefix,
)


def test_generate_token_format() -> None:
    plaintext = generate_token("apg_ing_")
    assert plaintext.startswith("apg_ing_")
    assert len(plaintext) == 40
    assert token_prefix(plaintext) == plaintext[:12]


def test_hash_token_is_sha256_hex() -> None:
    digest = hash_token("apg_ing_example")
    assert digest == hashlib.sha256(b"apg_ing_example").hexdigest()
    assert len(digest) == 64


def test_derive_key_is_deterministic_and_purpose_specific() -> None:
    first = derive_key("s" * 32, b"args-hash")
    second = derive_key("s" * 32, b"args-hash")
    other = derive_key("s" * 32, b"connection-secrets")
    assert first == second
    assert first != other
    assert len(first) == 32


def test_secretbox_round_trip() -> None:
    box = SecretBox("k" * 32, None)
    token = box.encrypt(b'{"host":"https://example.test"}')
    assert box.decrypt(token) == b'{"host":"https://example.test"}'
    assert box.needs_reencrypt(token) is False


def test_secretbox_previous_key_fallback_and_needs_reencrypt() -> None:
    previous = SecretBox("a" * 32, None)
    token = previous.encrypt(b"secret-config")
    current = SecretBox("b" * 32, "a" * 32)
    assert current.decrypt(token) == b"secret-config"
    assert current.needs_reencrypt(token) is True
    fresh = current.encrypt(b"secret-config")
    assert current.needs_reencrypt(fresh) is False


def test_secretbox_rejects_tampered_ciphertext() -> None:
    box = SecretBox("k" * 32, None)
    token = box.encrypt(b"payload")
    padded = token + ("=" * (-len(token) % 4))
    raw = bytearray(base64.urlsafe_b64decode(padded))
    raw[-1] ^= 0x01
    tampered = base64.urlsafe_b64encode(bytes(raw)).decode().rstrip("=")
    with pytest.raises(DecryptionError):
        box.decrypt(tampered)


def test_hmac_sha256_matches_stdlib() -> None:
    import hmac

    mac = hmac_sha256(b"key", b"data")
    assert mac == hmac.new(b"key", b"data", hashlib.sha256).digest()
