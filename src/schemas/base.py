"""Base record types shared by every domain."""
from __future__ import annotations

from typing import Any, ClassVar, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, model_validator

Severity = Literal["critical", "high", "medium", "low", "info"]
SEVERITY_ORDER: Tuple[str, ...] = ("critical", "high", "medium", "low", "info")


class Record(BaseModel):
    """A domain record.

    Declared fields are the contract components rely on (required + typed).
    Extra fields are allowed so additive CLI changes never break the TUI.
    Numeric strings coerce to int where a field is declared int (e.g. ``pid``).
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Finding(Record):
    """A record that is also a finding.

    Subclasses map their native fields onto the canonical ``id``/``title``/
    ``severity`` that FindingList and SeverityChips bind to:

    * ``SEVERITY_FIELD``: native field holding the level (``severity`` or ``risk``)
    * ``SEVERITY_MAP``: native value -> canonical severity (case-insensitive)
    * ``ID_FIELDS`` / ``TITLE_FIELDS``: first present native field wins
    """

    SEVERITY_FIELD: ClassVar[str] = "severity"
    SEVERITY_MAP: ClassVar[Dict[str, str]] = {s: s for s in SEVERITY_ORDER}
    ID_FIELDS: ClassVar[Tuple[str, ...]] = ("rule_id", "check_id", "id")
    TITLE_FIELDS: ClassVar[Tuple[str, ...]] = ("title", "item", "description")

    id: str
    title: str
    severity: Severity
    native_severity: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        native = data.get(cls.SEVERITY_FIELD)
        if native is not None and "native_severity" not in data:
            data["native_severity"] = str(native)
            mapped = cls.SEVERITY_MAP.get(str(native).lower())
            if mapped is None:
                raise ValueError(
                    f"{cls.__name__}: unknown {cls.SEVERITY_FIELD} {native!r}; "
                    f"expected one of {sorted(cls.SEVERITY_MAP)}"
                )
            data["severity"] = mapped
        if "id" not in data:
            # an ID_FIELDS entry may be composite: "service+client" -> "svc:client"
            for spec in cls.ID_FIELDS:
                parts = [data.get(f) for f in spec.split("+")]
                if all(parts):
                    data["id"] = ":".join(str(p) for p in parts)
                    break
        if "title" not in data or cls.TITLE_FIELDS[0] != "title":
            data.setdefault("title", next((str(data[f]) for f in cls.TITLE_FIELDS if data.get(f)), ""))
        if not data.get("id"):
            data["id"] = data.get("title", "")
        return data
