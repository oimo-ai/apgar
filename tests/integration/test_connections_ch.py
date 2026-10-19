from __future__ import annotations

from datetime import timedelta

import pytest

from apgar.security import SecretBox
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.secrets import seal_config
from apgar.worker.reencrypt import reencrypt_connections
from tests.factories import make_connection
from tests.support import ChDatabase

pytestmark = pytest.mark.integration


async def test_encrypted_at_rest_and_rotation(ch_database: ChDatabase, fixed_now: object) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _settings, _event, meta = ch_database
    connection = make_connection(
        fixed_now,
        config={"host": "https://cloud.langfuse.com", "public_key": "pk", "secret_key": "sk-test"},
    )
    await meta.upsert_connection(connection)
    raw = await meta.connection_ciphertext(connection.id)
    assert raw is not None
    assert not raw.lstrip().startswith("{")
    loaded = await meta.get_connection(connection.id)
    assert loaded is not None
    assert loaded.config["secret_key"] == "sk-test"
    await meta.delete_connection(connection.id, fixed_now + timedelta(milliseconds=1))
    previous = SecretBox("a" * 32, None)
    current = SecretBox("b" * 32, "a" * 32)
    rotated = ClickHouseMetaStore(meta.client, current)
    sealed = seal_config({"host": "https://example.test", "token": "old-token"}, previous)
    older = make_connection(
        fixed_now,
        id="00000000-0000-4000-8000-0000000000c2",
        name="rotated",
        config={"host": "https://example.test", "token": "old-token"},
    )
    await meta.client.insert(
        "connections",
        [
            [
                older.id,
                older.name,
                older.type.value,
                sealed,
                older.status.value,
                None,
                "",
                older.created_at,
                older.updated_at,
                0,
            ]
        ],
        column_names=[
            "id",
            "name",
            "type",
            "config_encrypted",
            "status",
            "last_checked_at",
            "last_error",
            "created_at",
            "updated_at",
            "is_deleted",
        ],
    )
    assert current.needs_reencrypt(await rotated.connection_ciphertext(older.id) or "")
    count = await reencrypt_connections(rotated, current, fixed_now + timedelta(seconds=1))
    assert count >= 1
    fresh = await rotated.connection_ciphertext(older.id)
    assert fresh is not None
    assert current.needs_reencrypt(fresh) is False
    only_new = ClickHouseMetaStore(meta.client, SecretBox("b" * 32, None))
    restored = await only_new.get_connection(older.id)
    assert restored is not None
    assert restored.config["token"] == "old-token"
