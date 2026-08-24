from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schemas" / "transaction.schema.json"
TRANSACTION_SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(TRANSACTION_SCHEMA)


def validate_transaction_document(document: dict[str, Any]) -> None:
    errors = sorted(_VALIDATOR.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "$"
        raise ValueError(f"Schema validation failed at {path}: {first.message}")
