"""Phase 0 enforcement: drift, output contracts, bindings, coverage, fixture hygiene."""
import copy
import getpass
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.tui_manifest import (
    FIXTURES, REPO, PageSpec, check_bindings, check_contracts, check_drift, check_pages, coverage,
    load_commands, load_components, load_labels, load_pages, load_seed, load_templates,
)


@pytest.fixture(scope="module")
def commands():
    return load_commands()


@pytest.fixture(scope="module")
def components():
    return load_components()


@pytest.fixture(scope="module")
def pages():
    return load_pages()


def _script(name, *args):
    return subprocess.run([sys.executable, str(REPO / "scripts" / name), *args], capture_output=True, text=True)


# ------------------------------------------------------------------- drift

def test_seed_matches_the_cli_parsers():
    result = _script("seed_manifest.py", "--check")
    assert result.returncode == 0, result.stderr


def test_every_cli_action_has_exactly_one_manifest_entry(commands):
    assert check_drift(load_seed(), commands) == []


def test_drift_detects_missing_and_orphan_entries(commands):
    trimmed = dict(commands)
    removed = trimmed.pop("net.list")
    orphan = removed.model_copy(update={"id": "net.nonexistent"})
    trimmed[orphan.id] = orphan
    problems = check_drift(load_seed(), trimmed)
    assert "CLI action without manifest entry: net.list" in problems
    assert "manifest entry without CLI action: net.nonexistent" in problems


# --------------------------------------------------------------- contracts

def test_every_fixture_satisfies_its_command_contract(commands):
    assert check_contracts(commands) == []


def test_empty_fixtures_need_a_sample_to_count(commands, tmp_path):
    # copy fixtures without samples: empty captures must then be reported
    for path in FIXTURES.glob("*.json"):
        (tmp_path / path.name).write_text(path.read_text())
    problems = check_contracts(commands, fixtures=tmp_path)
    assert "tcc.audit: empty-unverified" in problems


def test_mutating_commands_must_emit_results(commands):
    entry = commands["firewall.set"].model_dump()
    entry["emits"] = "Collection[Socket]"
    with pytest.raises(ValidationError):
        type(commands["firewall.set"]).model_validate(entry)


# ---------------------------------------------------------------- bindings

def test_all_page_bindings_type_check(pages, commands, components):
    assert check_bindings(pages, commands, components) == []


def _firewall_page(pages):
    return copy.deepcopy(pages["security.firewall"].model_dump())


@pytest.mark.parametrize("mutate, expected", [
    # a collection cannot render as status pills
    (lambda p: p["slots"][1].update(select="apps"), "projects to 'collection'"),
    # firewall app rules are not findings
    (lambda p: p["slots"][3].update(component="FindingList"), "projects to 'collection'"),
    (lambda p: p["slots"][3].update(component="NoSuchWidget"), "unknown component"),
    (lambda p: p["slots"][2].update(select="{bad"), "invalid select"),
    (lambda p: p["runs"][0].update(command="firewall.nope"), "unknown command"),
])
def test_bindings_reject_mismatches(pages, commands, components, mutate, expected):
    page = _firewall_page(pages)
    mutate(page)
    problems = check_bindings({"p": PageSpec.model_validate(page)}, commands, components)
    assert any(expected in problem for problem in problems), problems


@pytest.mark.parametrize("mutate", [
    lambda p: p["slots"].reverse(),                                   # not in composition order
    lambda p: p["slots"][1].update(run="missing"),                    # unknown run
    lambda p: p["runs"][0].update(depends_on=["toggle"]) or p["runs"][1].update(depends_on=["fw"]),  # cycle
])
def test_pages_enforce_order_references_and_acyclic_runs(pages, mutate):
    page = _firewall_page(pages)
    mutate(page)
    with pytest.raises(ValidationError):
        PageSpec.model_validate(page)


def test_pages_use_known_templates_regions_and_links(pages):
    from src.tui_v2 import VIEWS
    assert check_pages(pages, load_templates(), load_labels(), tuple(v.id for v in VIEWS)) == []


@pytest.mark.parametrize("mutate, expected", [
    (lambda p: p["page"].update(template="nope"), "unknown template"),
    (lambda p: p["page"].update(template="dashboard"), "has no workspace.aside region"),
    (lambda p: p["page"].update(concern="misc"), "unknown concern"),
    (lambda p: p["slots"][3]["props"].update(link="nowhere"), "link to unknown page"),
])
def test_page_checks_reject_bad_templates_regions_and_links(pages, mutate, expected):
    page = _firewall_page(pages)
    mutate(page)
    problems = check_pages({"p": PageSpec.model_validate(page)}, load_templates(), load_labels())
    assert any(expected in problem for problem in problems), problems


def test_prop_actions_must_reference_page_runs(pages):
    page = _firewall_page(pages)
    page["slots"][2]["props"]["on"]["run"] = "ghost"
    with pytest.raises(ValidationError):
        PageSpec.model_validate(page)


# ----------------------------------------------------------------- coverage

def test_coverage_report_is_fresh():
    result = _script("coverage_report.py", "--check")
    assert result.returncode == 0, result.stderr


def test_fallback_pages_never_count_as_coverage(commands, pages):
    page = _firewall_page(pages)
    page["page"]["fallback"] = True
    rows = coverage(commands, {"fb": PageSpec.model_validate(page)})
    assert {r["status"] for r in rows if r["id"] == "firewall.status"} == {"fallback-only"}


# ----------------------------------------------------------- fixture hygiene

def test_committed_fixtures_contain_no_host_identifiers():
    identifiers = {getpass.getuser(), socket.gethostname().split(".")[0], str(Path.home())}
    identifiers = {i for i in identifiers if i and len(i) > 2 and i not in {"user", "localhost"}}
    leaks = []
    for path in list(FIXTURES.glob("*.json")) + list((FIXTURES / "samples").glob("*.json")):
        text = path.read_text()
        leaks += [f"{path.name}: {i}" for i in identifiers if i in text]
    assert leaks == []
