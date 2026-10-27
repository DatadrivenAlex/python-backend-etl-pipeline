"""Application failures that are not row-level business rejections."""

from __future__ import annotations


class IdempotencyConflict(Exception):
    """The key was already stored for a different request body."""

    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"Idempotency-Key {key!r} was already used with a different request body"
        )


class DuplicateIdempotencyKey(Exception):
    """Another transaction inserted this key first. The caller retries the read."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)
