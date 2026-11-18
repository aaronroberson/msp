"""Generic envelopes: the operation kind a command performed (plan §3.2).

Every command output is typed as ``Envelope[Record]``. The envelope is the
same across command groups; the record is the group's domain noun. Facets
(``errors``, ``access_errors``, ``meta``) ride on every envelope and are bound
separately by the TUI (usually to the notice region).
"""
from __future__ import annotations

from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .base import Record

R = TypeVar("R", bound=Record)


class Envelope(BaseModel):
    """Fields shared by every envelope."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    access_errors: List[Any] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class Collection(Envelope, Generic[R]):
    """Query many: uniform records."""

    kind: Literal["collection"] = "collection"
    data: List[R]


class Item(Envelope, Generic[R]):
    """Query one / current state. May embed collections reached by projection."""

    kind: Literal["item"] = "item"
    data: R


class Findings(Envelope, Generic[R]):
    """Analysis results; every record exposes canonical id/title/severity."""

    kind: Literal["findings"] = "findings"
    data: List[R]


class Definitions(Envelope, Generic[R]):
    """A named catalog (presets, workflows, chains, providers)."""

    kind: Literal["definitions"] = "definitions"
    data: List[R]


class Diff(Envelope, Generic[R]):
    """Before/after comparison rows."""

    kind: Literal["diff"] = "diff"
    data: List[R]


class Run(Envelope, Generic[R]):
    """An executed (or planned) sequence of steps."""

    kind: Literal["run"] = "run"
    data: List[R]


class Stream(Envelope, Generic[R]):
    """Events observed over time. ``data`` holds the events received so far."""

    kind: Literal["stream"] = "stream"
    data: List[R] = Field(default_factory=list)


class ResultRecord(Record):
    ok: bool
    message: str = ""
    target: Optional[str] = None


class Result(Envelope):
    """Outcome of a mutation."""

    kind: Literal["result"] = "result"
    data: ResultRecord


class DocumentRecord(Record):
    format: Literal["text", "markdown"] = "text"
    text: str


class Document(Envelope):
    """Narrative output (reports, AI answers, text-only commands)."""

    kind: Literal["document"] = "document"
    data: DocumentRecord


ENVELOPES = {
    "Collection": Collection,
    "Item": Item,
    "Findings": Findings,
    "Definitions": Definitions,
    "Diff": Diff,
    "Run": Run,
    "Stream": Stream,
    "Result": Result,
    "Document": Document,
}
