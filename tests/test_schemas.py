"""Unit tests for the output-contract schemas (src/schemas)."""
import pytest
from pydantic import ValidationError

from src.schemas import EncodingError, normalize, resolve, validate_output


def test_resolve_builds_parameterized_envelopes():
    assert resolve("Collection[Socket]").__name__ == "Collection[Socket]"
    assert resolve("Result").__name__ == "Result"


@pytest.mark.parametrize("ref", [
    "Findings[Socket]",      # Findings needs a Finding record
    "Collection",            # generic envelope without record
    "Result[Socket]",        # non-generic envelope with record
    "Nope[Socket]",
    "Collection[Nope]",
    "not a ref",
])
def test_resolve_rejects_bad_references(ref):
    with pytest.raises(KeyError):
        resolve(ref)


def test_normalize_encodings():
    assert normalize([1], encoding="list") == {"data": [1]}
    assert normalize(["/a"], encoding="scalar-list", scalar_field="path") == {"data": [{"path": "/a"}]}
    assert normalize({"x": {"d": 1}}, encoding="keyed", key_field="key") == {"data": [{"key": "x", "d": 1}]}
    wrapped = normalize({"items": [1], "scope": "user", "access_errors": ["denied"]}, encoding="wrapped", data_key="items")
    assert wrapped == {"data": [1], "errors": [], "access_errors": ["denied"], "meta": {"scope": "user"}}
    obj = normalize({"a": 1, "errors": [{"e": 1}]}, encoding="object")
    assert obj["data"] == {"a": 1} and obj["errors"] == [{"e": 1}]
    assert normalize("hi", encoding="text", text_format="markdown") == {"data": {"format": "markdown", "text": "hi"}}


@pytest.mark.parametrize("raw, kwargs", [
    ({"a": 1}, {"encoding": "list"}),
    ([1], {"encoding": "keyed"}),
    ({"a": 1}, {"encoding": "wrapped", "data_key": "items"}),
    ({"a": 1}, {"encoding": "wrapped"}),
    (["x"], {"encoding": "text"}),
])
def test_normalize_rejects_mismatched_encodings(raw, kwargs):
    with pytest.raises(EncodingError):
        normalize(raw, **kwargs)


def test_records_coerce_declared_types_and_keep_extras():
    env = validate_output([{"process": "p", "pid": "42", "local": "*:1", "remote": "r", "extra": 1}],
                          "Collection[Connection]", encoding="list")
    assert env.data[0].pid == 42
    assert env.data[0].model_extra == {"extra": 1}


def test_records_require_declared_fields():
    with pytest.raises(ValidationError):
        validate_output([{"process": "p", "pid": 1, "local": "*:1"}], "Collection[Connection]", encoding="list")


@pytest.mark.parametrize("ref, row, native, canonical", [
    ("Findings[ShellFinding]", {"rule_id": "r", "title": "t", "severity": "WARNING"}, "WARNING", "medium"),
    ("Findings[StartupRisk]", {"item": "agent", "risk": "REVIEW", "reasons": []}, "REVIEW", "medium"),
    ("Findings[RuleFinding]", {"rule_id": "SH-1", "title": "t", "severity": "critical"}, "critical", "critical"),
])
def test_findings_expose_canonical_severity(ref, row, native, canonical):
    finding = validate_output([row], ref, encoding="list").data[0]
    assert (finding.native_severity, finding.severity) == (native, canonical)
    assert finding.id and finding.title


def test_findings_reject_unknown_severity_vocabulary():
    with pytest.raises(ValidationError):
        validate_output([{"item": "x", "risk": "SEVERE"}], "Findings[StartupRisk]", encoding="list")


def test_envelopes_forbid_unknown_top_level_fields():
    with pytest.raises(ValidationError):
        resolve("Collection[Socket]").model_validate({"data": [], "surprise": 1})


def test_exit_encoding_builds_a_result_from_the_exit_code():
    ok = validate_output("Firewall enabled\n", "Result", encoding="exit", returncode=0)
    assert (ok.data.ok, ok.data.message) == (True, "Firewall enabled")
    failed = validate_output("", "Result", encoding="exit", returncode=2)
    assert failed.data.ok is False
    accepted = validate_output("", "Result", encoding="exit", returncode=1, success_codes=(0, 1))
    assert accepted.data.ok is True
    with pytest.raises(EncodingError):
        normalize("x", encoding="exit")


def test_lines_encoding_feeds_streams():
    env = validate_output("a\n\n b \n", "Stream[Line]", encoding="lines")
    assert [line.text for line in env.data] == ["a", " b "]


def test_unverified_accepts_any_record():
    env = validate_output([{"anything": 1}], "Collection[Unverified]", encoding="list")
    assert env.data[0].model_extra == {"anything": 1}
