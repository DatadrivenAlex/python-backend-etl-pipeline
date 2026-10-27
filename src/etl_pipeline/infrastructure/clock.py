"""System time and ids. Tests can pass their own stand-ins to the service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdFactory:
    def new(self) -> str:
        return str(uuid.uuid4())
