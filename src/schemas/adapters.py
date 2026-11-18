"""Normalize a command's wire encoding into an envelope payload (plan §3.1, P0.2).

The CLI's JSON is not changed. A CommandSpec declares how its output arrives
(``encoding``, ``data_key``, ``key_field``, ``scalar_field``); ``normalize``
turns that into ``{"data": ..., "errors": [...], "access_errors": [...],
"meta": {...}}`` which the ``Envelope[Record]`` model then validates.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

Encoding = Literal["list", "keyed", "wrapped", "scalar-list", "object", "text"]
FACET_KEYS = ("errors", "access_errors")


class EncodingError(ValueError):
    pass


def _split_facets(obj: Dict[str, Any], data_key: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {key: obj.get(key) or [] for key in FACET_KEYS}
    payload["meta"] = {
        key: value for key, value in obj.items()
        if key not in FACET_KEYS and key != data_key
    }
    return payload


def normalize(
    raw: Any,
    *,
    encoding: Encoding,
    data_key: Optional[str] = None,
    key_field: str = "name",
    scalar_field: str = "value",
    text_format: str = "text",
) -> Dict[str, Any]:
    if encoding == "text":
        if not isinstance(raw, str):
            raise EncodingError(f"text encoding expects str, got {type(raw).__name__}")
        return {"data": {"format": text_format, "text": raw}}
    if encoding == "list":
        if not isinstance(raw, list):
            raise EncodingError(f"list encoding expects a JSON array, got {type(raw).__name__}")
        return {"data": raw}
    if encoding == "scalar-list":
        if not isinstance(raw, list):
            raise EncodingError(f"scalar-list encoding expects a JSON array, got {type(raw).__name__}")
        return {"data": [{scalar_field: item} for item in raw]}
    if not isinstance(raw, dict):
        raise EncodingError(f"{encoding} encoding expects a JSON object, got {type(raw).__name__}")
    if encoding == "keyed":
        return {"data": [{key_field: key, **value} for key, value in raw.items()]}
    if encoding == "wrapped":
        if not data_key:
            raise EncodingError("wrapped encoding requires data_key")
        if data_key not in raw:
            raise EncodingError(f"wrapped encoding: missing data_key {data_key!r} (keys: {sorted(raw)})")
        return {"data": raw[data_key], **_split_facets(raw, data_key)}
    if encoding == "object":
        payload = _split_facets(raw)
        payload["data"] = {key: value for key, value in raw.items() if key not in FACET_KEYS}
        payload["meta"] = {}
        return payload
    raise EncodingError(f"unknown encoding {encoding!r}")
