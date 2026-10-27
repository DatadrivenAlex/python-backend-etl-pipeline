"""Composition root shared by the API process and the CLI."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from etl_pipeline.application.load_service import LoadService
from etl_pipeline.application.transform import InvoiceTransformer
from etl_pipeline.config import Settings
from etl_pipeline.infrastructure.clock import SystemClock, UuidIdFactory
from etl_pipeline.infrastructure.metrics import Metrics
from etl_pipeline.infrastructure.persistence.db import build_session_factory, init_db, make_engine
from etl_pipeline.infrastructure.persistence.repositories import SqlUnitOfWork
from etl_pipeline.logging import configure_logging


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    metrics: Metrics
    session_factory: sessionmaker[Session]
    clock: SystemClock
    ids: UuidIdFactory
    transformer: InvoiceTransformer

    def unit_of_work(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.session_factory, self.clock)

    def load_service(self) -> LoadService:
        return LoadService(
            uow_factory=self.unit_of_work,
            transformer=self.transformer,
            metrics=self.metrics,
            ids=self.ids,
            clock=self.clock,
        )


def build_runtime(settings: Settings, engine: Engine | None = None) -> Runtime:
    configure_logging(settings.log_level)
    bound = engine or make_engine(settings.database_url, settings.db_pool_size)
    init_db(bound, retries=settings.db_startup_retries)
    return Runtime(
        settings=settings,
        engine=bound,
        metrics=Metrics(),
        session_factory=build_session_factory(bound),
        clock=SystemClock(),
        ids=UuidIdFactory(),
        transformer=InvoiceTransformer(),
    )
