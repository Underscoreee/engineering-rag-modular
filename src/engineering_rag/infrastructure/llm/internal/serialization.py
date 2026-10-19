"""Strict JSON envelopes and provider-only schema adaptation, never schema mutation."""

import json
from copy import deepcopy

from .errors import LLMError, LLMOutputError


def strict_json_object(raw: bytes | str) -> dict[str, object]:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError("nonfinite JSON constant")

    try:
        parsed = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)
        if not isinstance(parsed, dict):
            raise ValueError("JSON output must be an object")
        # Reject unpaired escaped surrogate characters as well as invalid UTF-8.
        json.dumps(parsed, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return parsed
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise LLMOutputError("invalid_json") from None


def provider_strict_schema(schema: dict[str, object]) -> dict[str, object]:
    """Require object properties on the wire only; preserve literal field names.

    This implements a conservative common strict-output subset, not a claim
    that an arbitrary provider accepts every JSON Schema keyword. Open/free-form
    object maps cannot safely be changed to closed objects and are rejected.
    """

    def adapt(node: object) -> object:
        if not isinstance(node, dict):
            return deepcopy(node)
        result: dict[str, object] = {}
        for key, value in node.items():
            if key == "default":
                continue
            if key in {"properties", "$defs", "definitions", "patternProperties"}:
                if not isinstance(value, dict):
                    raise LLMError("unsupported_schema")
                result[key] = {name: adapt(child) for name, child in value.items()}
            elif key in {"items", "contains", "additionalProperties", "not", "if", "then", "else"}:
                result[key] = adapt(value)
            elif key in {"anyOf", "oneOf", "allOf", "prefixItems"}:
                if not isinstance(value, list):
                    raise LLMError("unsupported_schema")
                result[key] = [adapt(child) for child in value]
            else:
                result[key] = deepcopy(value)
        if result.get("type") == "object" or "properties" in result:
            additional = result.get("additionalProperties")
            if additional is True or isinstance(additional, dict) or "patternProperties" in result:
                raise LLMError("unsupported_schema")
            properties = result.setdefault("properties", {})
            if not isinstance(properties, dict):
                raise LLMError("unsupported_schema")
            result["required"] = list(properties)
            result["additionalProperties"] = False
        return result

    result = adapt(schema)
    if not isinstance(result, dict) or result.get("type") != "object":
        raise LLMError("unsupported_schema")
    return result
