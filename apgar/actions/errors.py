from __future__ import annotations


class RetryableDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    def __init__(self, status: object, body: str | None = None) -> None:
        self.status = status
        self.body = "" if body is None else body
        if body is None:
            super().__init__(str(status))
        else:
            super().__init__(f"HTTP {status}: {body}"[:500])
