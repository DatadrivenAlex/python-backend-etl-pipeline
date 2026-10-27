"""Uvicorn entrypoint: `uvicorn etl_pipeline.api.asgi:app`."""

from etl_pipeline.api.app import create_app

app = create_app()
