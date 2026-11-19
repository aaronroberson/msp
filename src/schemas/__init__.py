"""Output contracts between msp commands and TUI components (plan §3.2, D10).

The CLI owns these models. ``resolve("Collection[Socket]")`` returns the
concrete pydantic model the manifest's ``emits`` refers to, and
``validate_output`` checks a command's raw JSON against it after normalizing
its wire encoding.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from .adapters import Encoding, EncodingError, normalize
from .base import SEVERITY_ORDER, Finding, Record
from .envelopes import ENVELOPES, Envelope
from .records import RECORDS

_REF = re.compile(r"^(?P<envelope>\w+)(?:\[(?P<record>\w+)\])?$")

__all__ = [
    "ENVELOPES", "RECORDS", "SEVERITY_ORDER", "Encoding", "EncodingError",
    "Envelope", "Finding", "Record", "normalize", "resolve", "validate_output",
]


@lru_cache(maxsize=None)
def resolve(ref: str) -> Type[BaseModel]:
    """``"Findings[StartupRisk]"`` -> ``Findings[StartupRisk]`` model; ``"Result"`` -> ``Result``."""
    match = _REF.match(ref.replace(" ", ""))
    if not match:
        raise KeyError(f"malformed envelope reference {ref!r}")
    envelope = ENVELOPES.get(match["envelope"])
    if envelope is None:
        raise KeyError(f"unknown envelope {match['envelope']!r} in {ref!r}")
    record_name = match["record"]
    if record_name is None:
        if envelope.__pydantic_generic_metadata__["parameters"]:
            raise KeyError(f"{ref!r}: envelope {match['envelope']} needs a record type")
        return envelope
    record = RECORDS.get(record_name)
    if record is None:
        raise KeyError(f"unknown record {record_name!r} in {ref!r}")
    if record_name and not envelope.__pydantic_generic_metadata__["parameters"]:
        raise KeyError(f"{ref!r}: envelope {match['envelope']} takes no record type")
    if envelope.__name__ == "Findings" and not issubclass(record, Finding):
        raise KeyError(f"{ref!r}: Findings requires a Finding record")
    return envelope[record]


def validate_output(
    raw: Any,
    emits: str,
    *,
    encoding: Encoding,
    data_key: Optional[str] = None,
    key_field: str = "name",
    scalar_field: str = "value",
    text_format: str = "text",
    returncode: Optional[int] = None,
    success_codes: tuple = (0,),
) -> Envelope:
    payload: Dict[str, Any] = normalize(
        raw, encoding=encoding, data_key=data_key, key_field=key_field,
        scalar_field=scalar_field, text_format=text_format,
        returncode=returncode, success_codes=success_codes,
    )
    return resolve(emits).model_validate(payload)
