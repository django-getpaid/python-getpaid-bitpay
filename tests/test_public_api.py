"""Tests for the public package API."""

import tomllib
from pathlib import Path

import getpaid_bitpay


def test_version() -> None:
    assert getpaid_bitpay.__version__ == "3.0.0a4"


def test_core_dependency_floor() -> None:
    pyproject_data = tomllib.loads(Path("pyproject.toml").read_text())
    assert (
        "python-getpaid-core>=3.0.0a4"
        in pyproject_data["project"]["dependencies"]
    )
