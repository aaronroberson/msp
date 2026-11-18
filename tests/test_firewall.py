"""Tests for firewall.py --listapps parsing and status plumbing."""
import subprocess
from unittest.mock import patch

from src import firewall
from src.firewall import _parse_app_list, status


SAMPLE_LISTAPPS = (
    "Total number of apps = 3\n"
    " 1 : /System/Applications/Utilities/DeviceHub.app \n"
    "    (Allow incoming connections)\n"
    " 2 : /Applications/Studio by Spotify Labs.app \n"
    "    (Block incoming connections)\n"
    " 3 : /Applications/Messages.app \n"
    "    (Allow incoming connections)\n"
)


def test_parse_app_list_pairs_path_with_verdict():
    apps = _parse_app_list(SAMPLE_LISTAPPS)
    assert apps == [
        {"path": "/System/Applications/Utilities/DeviceHub.app", "name": "DeviceHub.app", "status": "ALLOW"},
        {"path": "/Applications/Studio by Spotify Labs.app", "name": "Studio by Spotify Labs.app", "status": "BLOCK"},
        {"path": "/Applications/Messages.app", "name": "Messages.app", "status": "ALLOW"},
    ]


def test_parse_app_list_empty_and_garbage():
    assert _parse_app_list("Total number of apps = 0 \n") == []
    assert _parse_app_list("") == []
    # orphan verdict without a preceding path is skipped
    assert _parse_app_list("   (Allow incoming connections)\n") == []
    # unknown verdict format is skipped but does not kill pending path pairing
    assert _parse_app_list("1 : /Applications/App.app\n    (Weird verdict)\n") == []


def test_parse_app_list_handles_spaces_in_paths():
    text = (
        "Total number of apps = 1\n"
        " 1 : /Applications/My App Folder/Tool.app\n"
        "    (Block incoming connections)\n"
    )
    assert _parse_app_list(text) == [{
        "path": "/Applications/My App Folder/Tool.app",
        "name": "Tool.app",
        "status": "BLOCK",
    }]


def _fake_run(responses: dict[str, tuple[int, str]]):
    def fake(argv, privileged=False):
        option = argv[-1]
        code, text = responses.get(option, (0, ""))
        return subprocess.CompletedProcess(argv, code, text, "")
    return fake


def test_status_populates_structured_apps_and_raw_output():
    responses = {
        "--getglobalstate": (0, "Firewall is enabled. (State = 1)"),
        "--getstealthmode": (0, "Firewall stealth mode is on"),
        "--getblockall": (0, "Firewall has block all state set to disabled."),
        "--getallowsigned": (0, "Automatically allow built-in signed software ENABLED.\nAutomatically allow downloaded signed software DISABLED."),
        "--listapps": (0, SAMPLE_LISTAPPS),
    }
    with patch.object(firewall, "_run", _fake_run(responses)):
        result = status()
    assert result["available"] is True
    assert result["enabled"] is True
    assert result["stealth_mode"] is True
    assert result["block_all"] is False
    assert result["allows_signed"] is True
    assert result["allows_signed_app"] is False
    assert result["apps"] == _parse_app_list(SAMPLE_LISTAPPS)
    assert "DeviceHub.app" in result["apps_output"]


def test_status_marks_error_keys_on_nonzero_exit():
    responses = {
        "--getglobalstate": (1, "some failure"),
        "--getstealthmode": (1, ""),
        "--getblockall": (1, ""),
        "--getallowsigned": (1, ""),
    }
    with patch.object(firewall, "_run", _fake_run(responses)):
        result = status()
    assert result["enabled"] is None
    assert result["enabled_error"] == "some failure"
    assert result["stealth_mode"] is None


def test_status_unavailable_short_circuits(tmp_path):
    with patch.object(firewall, "SOCKETFILTERFW", str(tmp_path / "missing")):
        result = status()
    assert result == {"available": False, "apps": []}
