from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from apgar.security import SecretBox
from apgar.storage.interfaces import MetaStore

_LOG = logging.getLogger("apgar.worker")


async def reencrypt_connections(meta_store: MetaStore, box: SecretBox, now: datetime) -> int:
    ciphertext = getattr(meta_store, "connection_ciphertext", None)
    if ciphertext is None:
        return 0
    count = 0
    for connection in await meta_store.list_connections():
        raw = await ciphertext(connection.id)
        if not isinstance(raw, str) or raw == "":
            continue
        if not box.needs_reencrypt(raw):
            continue
        updated = replace(connection, updated_at=now)
        await meta_store.upsert_connection(updated)
        count += 1
    _LOG.info("re-encrypted %s connections", count)
    return count
