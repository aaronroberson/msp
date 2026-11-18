"""Parsing of `sharing -l` output (nested per-protocol blocks)."""
from src.sharing import parse_share_points

SAMPLE = """\t\t\tList of Share Points
name:\t\tPublic Folder
path:\t\t/Users/me/Public
\tsmb:\t{
    \t\tname:\tPublic Folder
    \t\tshared:\t1
    \t\tguest access:\t1
    \t\tread-only:\t0
    \t\tsealed:\t0
\t}

name:\t\tProjects
path:\t\t/Users/me/Projects
\tsmb:\t{
    \t\tname:\tProjects
    \t\tshared:\t1
    \t\tguest access:\t0
    \t\tread-only:\t1
\t}
"""


def test_nested_protocol_blocks_are_not_flattened():
    shares = parse_share_points(SAMPLE)
    assert [s["name"] for s in shares] == ["Public Folder", "Projects"]
    first = shares[0]
    assert first["path"] == "/Users/me/Public"
    assert first["protocols"]["smb"]["guest access"] == "1"
    assert "smb" not in first  # previously the literal "{"
    # lifted flags used by the table and --sort guest/readonly
    assert (first["guest_access"], first["read-only"]) == ("1", "0")
    assert (shares[1]["guest_access"], shares[1]["read-only"]) == ("0", "1")


def test_empty_output():
    assert parse_share_points("") == []

