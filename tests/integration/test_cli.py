import json
from pathlib import Path

from etl_pipeline.cli import main
from tests.conftest import FIXTURES


def _url(path: Path) -> str:
    return "sqlite+pysqlite:///" + path.resolve().as_posix()


def test_cli_loads_and_replays_a_csv(tmp_path: Path, capsys) -> None:
    database = _url(tmp_path / "etl.db")
    code = main(
        ["load", str(FIXTURES / "orders_sample.csv"), "--database-url", database]
    )
    assert code == 0
    first = json.loads(capsys.readouterr().out)
    assert first["accepted"] == 3
    assert first["rejected"] == 1
    assert first["inserted"] == 3
    assert first["rejections"][0]["code"] == "INVALID_QUANTITY"

    again = main(
        ["load", str(FIXTURES / "orders_sample.csv"), "--database-url", database]
    )
    assert again == 0
    second = json.loads(capsys.readouterr().out)
    assert second["load_id"] == first["load_id"]
    assert second["inserted"] == 3


def test_cli_conflict_and_missing_file(tmp_path: Path, capsys) -> None:
    database = _url(tmp_path / "etl.db")
    sample = FIXTURES / "orders_sample.csv"
    other = tmp_path / "other.csv"
    other.write_text(sample.read_text(encoding="utf-8").replace("INV-100", "INV-777"), encoding="utf-8")
    assert main(["load", str(sample), "--database-url", database, "--idempotency-key", "manual-key-1"]) == 0
    capsys.readouterr()
    code = main(
        ["load", str(other), "--database-url", database, "--idempotency-key", "manual-key-1"]
    )
    assert code == 3
    error = json.loads(capsys.readouterr().err)
    assert error["code"] == "IDEMPOTENCY_CONFLICT"

    missing = main(["load", str(tmp_path / "missing.csv"), "--database-url", database])
    assert missing == 2
