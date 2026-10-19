from __future__ import annotations

from datetime import timedelta

from apgar.security import SecretBox
from apgar.storage.memory import InMemoryMetaStore
from apgar.storage.secrets import seal_config
from apgar.worker.reencrypt import reencrypt_connections
from tests.factories import make_connection


async def test_reencrypt_at_startup(fixed_now: object) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    previous = SecretBox("a" * 32, None)
    current = SecretBox("b" * 32, "a" * 32)
    config = {"host": "https://cloud.langfuse.com", "public_key": "pk", "secret_key": "sk"}
    connection = make_connection(fixed_now, config=config)
    store = InMemoryMetaStore(current)
    store._sealed[connection.id] = seal_config(config, previous)
    store._connections[connection.id] = (connection, False)
    raw = await store.connection_ciphertext(connection.id)
    assert raw is not None
    assert current.needs_reencrypt(raw) is True
    count = await reencrypt_connections(store, current, fixed_now + timedelta(seconds=1))
    assert count == 1
    rotated = await store.connection_ciphertext(connection.id)
    assert rotated is not None
    assert current.needs_reencrypt(rotated) is False
    loaded = await store.get_connection(connection.id)
    assert loaded is not None
    assert loaded.config["secret_key"] == "sk"
