from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from mini_store.cli import main
from mini_store.diagnostics import health_report
from mini_store.output import quote_payload
from mini_store.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_exposes_working_console_script():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["name"] == "mini-store-long"
    assert metadata["project"]["dynamic"] == ["version"]
    assert metadata["project"]["scripts"]["mini-store"] == "mini_store.cli:main"
    assert metadata["tool"]["setuptools"]["packages"]["find"]["where"] == ["."]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "mini_store.version.VERSION"
    }


def test_cli_quote_applies_bulk_discount_then_tax(capsys):
    assert main(["quote", "--amount", "100", "--items", "10", "--tax-rate", "0.1"]) == 0
    assert capsys.readouterr().out.strip() == "99.00"


def test_python_module_entrypoint_runs_end_to_end():
    result = subprocess.run(
        [sys.executable, "-m", "mini_store", "quote", "--amount", "50", "--items", "2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "54.00"


def test_cli_structured_quote_contract(capsys):
    assert main(["quote", "--amount", "100", "--items", "10", "--tax-rate", "0.1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "amount": 100.0,
        "items": 10,
        "discount": 10.0,
        "tax": 9.0,
        "total": 99.0,
    }


def test_version_and_doctor_commands(capsys):
    assert VERSION == "0.2.0"
    assert health_report() == {"package": "mini_store", "status": "ok", "version": "0.2.0"}
    assert quote_payload(100.0, 10, tax_rate=0.1)["total"] == 99.0
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.2.0"
    assert main(["doctor"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "package": "mini_store",
        "status": "ok",
        "version": "0.2.0",
    }
