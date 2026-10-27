.PHONY: install test up down logs bench

install:
	python -m pip install -e ".[dev]"

test:
	pytest

bench:
	python scripts/bench_transform.py

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api
