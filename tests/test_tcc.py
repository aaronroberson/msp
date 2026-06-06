import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

from src.tcc import TCCManager


def create_tcc_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE access (
            service TEXT NOT NULL,
            client TEXT NOT NULL,
            client_type INTEGER NOT NULL,
            auth_value INTEGER NOT NULL,
            auth_reason INTEGER,
            auth_version INTEGER,
            csreq BLOB,
            policy_id INTEGER,
            indirect_object_identifier TEXT,
            indirect_object_identifier_type INTEGER,
            flags INTEGER,
            last_modified INTEGER,
            last_reminded INTEGER,
            prompt_count INTEGER,
            PRIMARY KEY (service, client, client_type)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO access (
            service, client, client_type, auth_value, auth_reason, auth_version,
            csreq, policy_id, indirect_object_identifier,
            indirect_object_identifier_type, flags, last_modified,
            last_reminded, prompt_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "kTCCServiceCamera",
            "com.example.CameraApp",
            0,
            2,
            3,
            1,
            b"abc",
            None,
            None,
            None,
            0,
            1700000000,
            1700000100,
            4,
        ),
    )
    conn.execute(
        """
        INSERT INTO access (
            service, client, client_type, auth_value, auth_reason, auth_version,
            csreq, policy_id, indirect_object_identifier,
            indirect_object_identifier_type, flags, last_modified,
            last_reminded, prompt_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "kTCCServiceMicrophone",
            "/usr/bin/say",
            1,
            1,
            3,
            1,
            None,
            None,
            None,
            None,
            0,
            1700000200,
            None,
            1,
        ),
    )
    conn.commit()
    conn.close()


class TCCTest(unittest.TestCase):
    def test_list_permissions_reads_custom_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "TCC.db"
            create_tcc_db(db_path)

            manager = TCCManager(db_path=str(db_path))
            with redirect_stdout(StringIO()):
                entries = manager.list_permissions()

            self.assertEqual(len(entries), 2)
            camera = entries[0]
            self.assertEqual(camera.service, "kTCCServiceCamera")
            self.assertEqual(camera.service_name, "Camera")
            self.assertEqual(camera.client, "com.example.CameraApp")
            self.assertIs(camera.allowed, True)
            self.assertEqual(camera.auth_status, "allowed")
            self.assertEqual(camera.prompt_count, 4)
            self.assertEqual(camera.csreq, "YWJj")

    def test_service_alias_and_client_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "TCC.db"
            create_tcc_db(db_path)

            manager = TCCManager(db_path=str(db_path))
            with redirect_stdout(StringIO()):
                entries = manager.list_permissions(service="mic", client="say")

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].service, "kTCCServiceMicrophone")
            self.assertEqual(entries[0].client_name, "say")
            self.assertIs(entries[0].allowed, False)

    def test_backup_writes_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "TCC.db"
            output_path = Path(temp_dir) / "backup.json"
            create_tcc_db(db_path)

            manager = TCCManager(db_path=str(db_path))
            with redirect_stdout(StringIO()):
                payload = manager.backup(output=str(output_path))
            written = json.loads(output_path.read_text(encoding="utf-8"))

            self.assertTrue(payload["permissions"])
            self.assertEqual(written["permissions"][0]["source"], "custom")
            self.assertEqual(written["errors"], [])


if __name__ == "__main__":
    unittest.main()
