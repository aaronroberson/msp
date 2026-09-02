import unittest
from pathlib import Path
from src.forensics import AppleDoubleParser, QuarantineParser, ProvenanceParser, SpotlightInspector, HostCorrelator


class TestForensics(unittest.TestCase):
    def test_quarantine_parser(self):
        # 0082;6a889aa4;QuickTime Player;
        raw = b"0082;6a889aa4;QuickTime Player;DBAF7794-A3E5-4D1B-AD84-8E05F5AB7517"
        res = QuarantineParser.parse(raw)
        self.assertEqual(res["flags"], "0082")
        self.assertEqual(res["hex_timestamp"], "6a889aa4")
        self.assertEqual(res["agent_app"], "QuickTime Player")
        self.assertEqual(res["uuid"], "DBAF7794-A3E5-4D1B-AD84-8E05F5AB7517")
        self.assertIn("2026-08-21", res["timestamp_utc"])

    def test_provenance_parser(self):
        raw = b"\xa4\x9a\x88j\x00\x00\x00\x00\xba]p%\x00\x00\x00\x000082;6a889aa4;QuickTime Player;\xdb\xafw\x94\xa3\xe5M\x1b\xad\x84\x8e\x05\xf5\xabu\x17"
        res = ProvenanceParser.parse(raw)
        self.assertIn("text_fragments", res)
        self.assertIn("QuickTime Player", "".join(res["text_fragments"]))
        self.assertEqual(res["probable_uuid"], "dbaf7794-a3e5-4d1b-ad84-8e05f5ab7517")

    def test_appledouble_parser_invalid(self):
        p = AppleDoubleParser("/non/existent/path")
        summary = p.get_summary()
        self.assertFalse(summary["valid"])

    def test_live_volume_scan_if_mounted(self):
        vol = Path("/Volumes/NO NAME")
        if vol.exists():
            spotlight = SpotlightInspector.inspect(vol)
            self.assertTrue(spotlight["spotlight_configured"])
            corr = HostCorrelator.correlate(vol)
            self.assertEqual(corr["score"], "DEFINITIVE_MATCH")


if __name__ == "__main__":
    unittest.main()
