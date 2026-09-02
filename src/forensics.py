#!/usr/bin/env python3
"""macOS Volume & File Forensics Module.

Inspects external drives, volumes, AppleDouble (._*) sidecars, extended attributes,
Spotlight stores, and correlates external artifact evidence against the local Mac host.

Usage:
    msp forensics <subcommand> [options]
    msp forensics scan <path>
    msp forensics correlate <volume>
    msp forensics spotlight <volume>
    msp forensics inspect <._file>
    msp forensics clean <path> [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import plistlib
import re
import struct
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from src.command import (
        interactive_menu as cmd_interactive_menu,
        interactive_select as cmd_interactive_select,
        setup_completion,
        suggest_command,
    )
except ImportError:
    cmd_interactive_menu = None
    cmd_interactive_select = None


class AppleDoubleParser:
    """Parses AppleDouble binary format v2 and extracts extended attributes."""

    MAGIC = 0x00051607

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.raw_data = b""
        self.valid = False
        self.entries: Dict[int, bytes] = {}
        self.xattrs: Dict[str, bytes] = {}
        self._load()

    def _load(self):
        if not self.path.exists() or not self.path.is_file():
            return
        try:
            self.raw_data = self.path.read_bytes()
        except Exception:
            return

        if len(self.raw_data) < 26:
            return

        magic, version, home_fs, num_entries = struct.unpack('>II16sH', self.raw_data[:26])
        if magic != self.MAGIC:
            return

        self.valid = True
        offset = 26
        for _ in range(num_entries):
            if offset + 12 > len(self.raw_data):
                break
            eid, eoffset, elength = struct.unpack('>III', self.raw_data[offset:offset+12])
            if eoffset + elength <= len(self.raw_data):
                self.entries[eid] = self.raw_data[eoffset:eoffset+elength]
            offset += 12

        self._parse_xattrs()

    def _parse_xattrs(self):
        # Entry 9 is Finder Info (starts with 32 bytes FinderInfo, then ATTR header if present)
        finfo_data = self.entries.get(9, b"")
        if not finfo_data:
            return

        attr_idx = finfo_data.find(b'ATTR')
        if attr_idx == -1:
            return

        attr_buf = finfo_data[attr_idx:]
        if len(attr_buf) < 36:
            return

        magic, debug_tag, total_size, data_start, data_length, flags, num_attrs = struct.unpack(
            '>4sIIII12xHH', attr_buf[:36]
        )
        if magic != b'ATTR':
            return

        cur = 36
        for _ in range(num_attrs):
            if cur + 11 > len(attr_buf):
                break
            a_offset, a_length, a_flags, a_namelen = struct.unpack('>IIHB', attr_buf[cur:cur+11])
            name_bytes = attr_buf[cur+11 : cur+11+a_namelen]
            name = name_bytes.decode('utf-8', errors='replace')
            cur += 11 + a_namelen
            if cur % 2 != 0:
                cur += 1

            if a_offset + a_length <= len(attr_buf):
                self.xattrs[name] = attr_buf[a_offset : a_offset + a_length]

    def get_summary(self) -> Dict[str, Any]:
        if not self.valid:
            return {"valid": False, "path": str(self.path)}

        summary: Dict[str, Any] = {
            "valid": True,
            "path": str(self.path),
            "size": len(self.raw_data),
            "mtime": datetime.datetime.fromtimestamp(self.path.stat().st_mtime, tz=datetime.timezone.utc).isoformat(),
            "xattr_names": list(self.xattrs.keys()),
            "parsed_xattrs": {},
        }

        # Decode quarantine
        if "com.apple.quarantine" in self.xattrs:
            summary["parsed_xattrs"]["quarantine"] = QuarantineParser.parse(self.xattrs["com.apple.quarantine"])

        # Decode provenance
        if "com.apple.provenance" in self.xattrs:
            summary["parsed_xattrs"]["provenance"] = ProvenanceParser.parse(self.xattrs["com.apple.provenance"])

        # Decode AVKit keys
        if "com.apple.avkit.thumbnailCacheIdentifier" in self.xattrs:
            val = self.xattrs["com.apple.avkit.thumbnailCacheIdentifier"]
            summary["parsed_xattrs"]["avkit_thumbnail_id"] = val.hex()

        if "com.apple.avkit.thumbnailCacheEncryptionKey" in self.xattrs:
            val = self.xattrs["com.apple.avkit.thumbnailCacheEncryptionKey"]
            summary["parsed_xattrs"]["avkit_encryption_key"] = val.hex()

        # Decode lastuseddate
        if "com.apple.lastuseddate#PS" in self.xattrs:
            summary["parsed_xattrs"]["lastuseddate_hex"] = self.xattrs["com.apple.lastuseddate#PS"].hex()

        return summary


class QuarantineParser:
    """Parses com.apple.quarantine string format."""

    @staticmethod
    def parse(raw_bytes: bytes) -> Dict[str, Any]:
        txt = raw_bytes.decode('utf-8', errors='ignore').strip('\x00')
        parts = txt.split(';')
        res: Dict[str, Any] = {"raw": txt}
        if len(parts) >= 3:
            res["flags"] = parts[0]
            hex_time = parts[1]
            res["hex_timestamp"] = hex_time
            try:
                ts = int(hex_time, 16)
                dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
                res["timestamp_utc"] = dt.isoformat()
            except Exception:
                res["timestamp_utc"] = None
            res["agent_app"] = parts[2]
            if len(parts) > 3:
                res["uuid"] = parts[3]
        return res


class ProvenanceParser:
    """Parses com.apple.provenance structure."""

    @staticmethod
    def parse(raw_bytes: bytes) -> Dict[str, Any]:
        res: Dict[str, Any] = {"raw_hex": raw_bytes.hex()}
        txt = raw_bytes.decode('ascii', errors='ignore')
        matches = re.findall(r'[\x20-\x7e]{4,}', txt)
        if matches:
            res["text_fragments"] = matches
        # Search for UUID patterns in raw bytes
        if len(raw_bytes) >= 16:
            try:
                tail = raw_bytes[-16:]
                res["probable_uuid"] = str(uuid.UUID(bytes=tail))
            except Exception:
                pass
        return res


class ExifToolInspector:
    """Extracts embedded EXIF/XMP/QuickTime metadata using exiftool if available."""

    @staticmethod
    def available() -> bool:
        import shutil
        return shutil.which("exiftool") is not None

    @staticmethod
    def inspect(file_path: Path | str) -> Dict[str, Any]:
        p = Path(file_path)
        if not p.exists():
            return {"available": False, "error": f"File {file_path} does not exist"}
        if not ExifToolInspector.available():
            return {
                "available": False,
                "note": "Install exiftool via 'brew install exiftool' for deep media metadata extraction.",
            }
        try:
            r = subprocess.run(
                ["exiftool", "-j", "-q", str(p)],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout.strip())
                if data and isinstance(data, list):
                    meta = data[0]
                    filtered = {}
                    keys_of_interest = [
                        "FileType", "MIMEType", "CreateDate", "ModifyDate", "TrackCreateDate", "TrackModifyDate",
                        "Make", "Model", "Software", "CompressorID", "VideoFrameRate", "ImageSize", "Duration",
                        "GPSPosition", "GPSLatitude", "GPSLongitude", "DeviceManufacturer", "CameraModelName"
                    ]
                    for k, v in meta.items():
                        if k in keys_of_interest or not k.startswith("Directory"):
                            filtered[k] = v
                    return {"available": True, "metadata": filtered}
        except Exception as e:
            return {"available": True, "error": str(e)}
        return {"available": True, "metadata": {}}


class SpotlightInspector:
    """Inspects external volume Spotlight stores and FSEvents records."""

    @staticmethod
    def inspect(volume_path: Path | str) -> Dict[str, Any]:
        vpath = Path(volume_path)
        res: Dict[str, Any] = {"volume_path": str(vpath)}

        plist_path = vpath / ".Spotlight-V100" / "VolumeConfiguration.plist"
        if plist_path.exists():
            try:
                with open(plist_path, "rb") as f:
                    pl = plistlib.load(f)
                res["spotlight_configured"] = True
                res["creation_version"] = pl.get("ConfigurationCreationVersion")
                cdate = pl.get("ConfigurationCreationDate")
                res["creation_date"] = cdate.isoformat() if cdate else None
                res["modification_version"] = pl.get("ConfigurationModificationVersion")
                mdate = pl.get("ConfigurationModificationDate")
                res["modification_date"] = mdate.isoformat() if mdate else None
                res["volume_uuid"] = pl.get("ConfigurationVolumeUUID")
                stores = pl.get("Stores", {})
                res["store_uuids"] = list(stores.keys())
            except Exception as e:
                res["spotlight_error"] = str(e)
        else:
            res["spotlight_configured"] = False

        fsevents_uuid = vpath / ".fseventsd" / "fseventsd-uuid"
        if fsevents_uuid.exists():
            try:
                res["fsevents_uuid"] = fsevents_uuid.read_text().strip()
            except Exception:
                pass

        return res


class HostCorrelator:
    """Correlates evidence from an external volume against this local Mac host."""

    @staticmethod
    def correlate(volume_path: Path | str) -> Dict[str, Any]:
        vpath = Path(volume_path)
        report: Dict[str, Any] = {
            "volume": str(vpath),
            "matches": [],
            "score": "NONE",
            "evidence": {}
        }

        # 1. Inspect Spotlight on the volume
        spotlight_info = SpotlightInspector.inspect(vpath)
        report["evidence"]["spotlight"] = spotlight_info

        # 2. Check Install History on current Mac
        install_history = Path("/Library/Receipts/InstallHistory.plist")
        matched_installs = []
        if install_history.exists():
            try:
                with open(install_history, "rb") as f:
                    pl = plistlib.load(f)
                c_ver = spotlight_info.get("creation_version", "")
                m_ver = spotlight_info.get("modification_version", "")
                for item in pl:
                    name = item.get("displayName", "")
                    ver = item.get("displayVersion", "")
                    date = item.get("date")
                    date_str = date.isoformat() if date else ""
                    if "macOS" in name:
                        if (ver and (ver in c_ver or ver in m_ver)) or (c_ver and ver in c_ver):
                            matched_installs.append({
                                "displayName": name,
                                "displayVersion": ver,
                                "date": date_str
                            })
            except Exception as e:
                report["evidence"]["install_history_error"] = str(e)

        if matched_installs:
            report["matches"].append("macOS Build Version Alignment")
            report["evidence"]["matched_os_installs"] = matched_installs

        # 3. Scan QuickTime preferences & Shared File Lists
        sfl_matches = []
        sfl_dir = Path.home() / "Library" / "Application Support" / "com.apple.sharedfilelist"
        for sfl in sfl_dir.rglob("*.sfl*"):
            try:
                data = sfl.read_bytes()
                if vpath.name.encode('utf-8') in data or b'MOVI' in data:
                    sfl_matches.append(str(sfl))
            except Exception:
                pass

        if sfl_matches:
            report["matches"].append("LaunchServices SharedFileList (SFL) Recent Item References")
            report["evidence"]["matched_sfl_files"] = sfl_matches

        # 4. Check QuickTime Player Container Plist
        qt_plist = Path.home() / "Library" / "Containers" / "com.apple.QuickTimePlayerX" / "Data" / "Library" / "Preferences" / "com.apple.QuickTimePlayerX.plist"
        if qt_plist.exists():
            try:
                with open(qt_plist, "rb") as f:
                    qpl = plistlib.load(f)
                bookmarks = qpl.get("MGRecentDocumentURLBookmarks", [])
                found_bookmarks = []
                for idx, bm in enumerate(bookmarks):
                    if isinstance(bm, bytes) and (vpath.name.encode('utf-8') in bm or b'VIDEO' in bm):
                        found_bookmarks.append(f"Bookmark #{idx+1}")
                if found_bookmarks:
                    report["matches"].append("QuickTime Player URL Bookmark Alignment")
                    report["evidence"]["quicktime_bookmarks"] = found_bookmarks
            except Exception as e:
                report["evidence"]["quicktime_error"] = str(e)

        # Scoring
        match_count = len(report["matches"])
        if match_count >= 3:
            report["score"] = "DEFINITIVE_MATCH"
        elif match_count == 2:
            report["score"] = "STRONG_MATCH"
        elif match_count == 1:
            report["score"] = "MODERATE_MATCH"
        else:
            report["score"] = "NO_LOCAL_CORRELATION"

        return report


class ForensicScanner:
    """Scans volumes or directories for forensic metadata and AppleDoubles."""

    @staticmethod
    def scan(target_path: Path | str) -> Dict[str, Any]:
        path = Path(target_path)
        if not path.exists():
            return {"error": f"Path {target_path} does not exist"}

        result: Dict[str, Any] = {
            "target": str(path),
            "scan_timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "appledouble_count": 0,
            "files": [],
        }

        # Search for ._* files
        ad_files = list(path.rglob("._*"))
        result["appledouble_count"] = len(ad_files)

        for ad in ad_files:
            # Skip hidden indexing folders if in Spotlight/fseventsd
            if ".Spotlight-V100" in str(ad) or ".fseventsd" in str(ad):
                continue
            parser = AppleDoubleParser(ad)
            summary = parser.get_summary()
            target_data_file = ad.parent / ad.name[2:]
            summary["data_file_exists"] = target_data_file.exists()
            if target_data_file.exists():
                try:
                    summary["data_file_size"] = target_data_file.stat().st_size
                    summary["data_file_mtime"] = datetime.datetime.fromtimestamp(
                        target_data_file.stat().st_mtime, tz=datetime.timezone.utc
                    ).isoformat()
                except Exception:
                    pass
            result["files"].append(summary)

        return result

    @staticmethod
    def clean_artifacts(target_path: Path | str, dry_run: bool = True, include_ds_store: bool = True) -> Dict[str, Any]:
        path = Path(target_path)
        removed = []
        # 1. Find orphaned AppleDouble files (._* where main data file is missing)
        for ad in path.rglob("._*"):
            if ".Spotlight" in str(ad) or ".fseventsd" in str(ad):
                continue
            data_file = ad.parent / ad.name[2:]
            if not data_file.exists():
                removed.append(str(ad))
                if not dry_run:
                    try:
                        ad.unlink()
                    except Exception:
                        pass

        # 2. Find .DS_Store files if requested
        if include_ds_store:
            for ds in path.rglob(".DS_Store"):
                removed.append(str(ds))
                if not dry_run:
                    try:
                        ds.unlink()
                    except Exception:
                        pass

        return {
            "target": str(path),
            "dry_run": dry_run,
            "count": len(removed),
            "removed_files": removed,
        }


def get_mounted_volumes() -> List[str]:
    """Returns list of mounted volumes in /Volumes."""
    vols = []
    vpath = Path("/Volumes")
    if vpath.exists():
        for d in vpath.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                vols.append(str(d))
    return vols


def interactive_menu(json_output: bool = False):
    """Interactive CLI menu for forensics module."""
    if not cmd_interactive_menu:
        print("Interactive menu not available. Please pass arguments directly (e.g. msp forensics scan /Volumes/NO\\ NAME)")
        return

    mounted = get_mounted_volumes()

    while True:
        action = cmd_interactive_menu([
            {"name": "🔍  Scan Volume or Directory for AppleDoubles & Extended Attributes", "value": "scan"},
            {"name": "🔗  Correlate Volume Evidence with Local Mac Host History", "value": "correlate"},
            {"name": "🧭  Inspect Volume Spotlight & FSEvents OS Configuration", "value": "spotlight"},
            {"name": "🔬  Deeply Inspect a Specific ._* AppleDouble File", "value": "inspect"},
            {"name": "🧹  Clean Stray Artifacts (Orphaned ._*, .DS_Store, etc.)", "value": "clean"},
            {"name": "❌  Exit", "value": "exit"},
        ], title="=== macOS Forensic & Metadata Analysis ===")

        if not action or action == "exit":
            break

        if action in ("scan", "correlate", "spotlight", "clean"):
            choices = [{"name": f"Volume: {v}", "value": v} for v in mounted]
            choices.append({"name": "Custom path...", "value": "__custom__"})
            selected_vol = cmd_interactive_select(choices, title=f"Select target for {action}:")
            if not selected_vol:
                continue
            if selected_vol == "__custom__":
                custom = input("Enter directory or volume path: ").strip()
                if not custom:
                    continue
                target_path = custom
            else:
                target_path = selected_vol

            if action == "scan":
                res = ForensicScanner.scan(target_path)
                if json_output:
                    print(json.dumps(res, indent=2))
                else:
                    print(f"\n[+] Found {res['appledouble_count']} AppleDouble files in {target_path}")
                    for f in res.get("files", [])[:20]:
                        print(f"  • {f['path']} ({f.get('size')} bytes)")
                        px = f.get("parsed_xattrs", {})
                        if "quarantine" in px:
                            print(f"    Quarantine: {px['quarantine'].get('agent_app')} @ {px['quarantine'].get('timestamp_utc')}")
                        if "provenance" in px:
                            print(f"    Provenance: UUID={px['provenance'].get('probable_uuid')}")
                    if len(res.get("files", [])) > 20:
                        print(f"  ... and {len(res.get('files', [])) - 20} more files.")

            elif action == "correlate":
                res = HostCorrelator.correlate(target_path)
                if json_output:
                    print(json.dumps(res, indent=2))
                else:
                    print(f"\n[+] Correlation Score: {res['score']}")
                    for m in res["matches"]:
                        print(f"  ✓ {m}")

            elif action == "spotlight":
                res = SpotlightInspector.inspect(target_path)
                if json_output:
                    print(json.dumps(res, indent=2))
                else:
                    print(f"\n[+] Spotlight Configured: {res.get('spotlight_configured')}")
                    print(f"  Creation Build: {res.get('creation_version')} ({res.get('creation_date')})")
                    print(f"  Modification Build: {res.get('modification_version')} ({res.get('modification_date')})")
                    print(f"  Volume UUID: {res.get('volume_uuid')}")

            elif action == "clean":
                dry = input("Dry run only? [Y/n]: ").strip().lower() != "n"
                res = ForensicScanner.clean_artifacts(target_path, dry_run=dry)
                print(f"\n[+] Cleaned {res['count']} artifact items (dry_run={dry})")
                for r in res["removed_files"]:
                    print(f"  - {r}")

        elif action == "inspect":
            fpath = input("Enter path to AppleDouble file (._*): ").strip()
            if fpath:
                p = AppleDoubleParser(fpath)
                print(json.dumps(p.get_summary(), indent=2))

        input("\nPress Enter to continue...")


def main():
    epilog_text = """
How to Use:
  1. Scan any external drive, USB stick, or SD card for AppleDoubles and metadata:
       msp forensics scan "/Volumes/NO NAME"
       msp forensics scan "/Volumes/NO NAME" --json

  2. Correlate external volume evidence against this Mac's host history:
       msp forensics correlate "/Volumes/NO NAME"

  3. Inspect external volume Spotlight stores and OS build history:
       msp forensics spotlight "/Volumes/NO NAME"

  4. Deeply inspect a specific ._* AppleDouble file:
       msp forensics inspect "/Volumes/NO NAME/VIDEO/._MOVI1787.avi"

  5. Clean stray metadata artifacts (orphaned ._* sidecars, .DS_Store):
       msp forensics clean "/Volumes/NO NAME" --dry-run
       msp forensics clean "/Volumes/NO NAME" --force

  6. Interactive Menu:
       msp forensics
"""
    parser = argparse.ArgumentParser(
        description="macOS Volume & File Forensics CLI",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Forensics subcommands")

    # scan
    scan_p = subparsers.add_parser("scan", help="Scan a volume or directory for AppleDoubles and metadata")
    scan_p.add_argument("path", help="Target path or mount point (e.g. /Volumes/NO NAME)")
    scan_p.add_argument("--json", action="store_true", help="Output JSON format")

    # inspect-file
    insp_p = subparsers.add_parser("inspect", help="Deeply inspect an AppleDouble file")
    insp_p.add_argument("file", help="Path to ._* AppleDouble file")
    insp_p.add_argument("--json", action="store_true", help="Output JSON format")

    # correlate
    corr_p = subparsers.add_parser("correlate", help="Correlate volume evidence with local Mac host")
    corr_p.add_argument("volume", help="Volume mount point (e.g. /Volumes/NO NAME)")
    corr_p.add_argument("--json", action="store_true", help="Output JSON format")

    # spotlight
    spot_p = subparsers.add_parser("spotlight", help="Inspect Spotlight configuration on external volume")
    spot_p.add_argument("volume", help="Volume mount point (e.g. /Volumes/NO NAME)")
    spot_p.add_argument("--json", action="store_true", help="Output JSON format")

    # clean
    clean_p = subparsers.add_parser("clean", help="Clean stray metadata artifacts (orphaned ._*, .DS_Store, etc.)")
    clean_p.add_argument("path", help="Target path to clean")
    clean_p.add_argument("--dry-run", action="store_true", default=True, help="Preview files to be deleted without removing")
    clean_p.add_argument("--force", action="store_false", dest="dry_run", help="Actually delete files")
    clean_p.add_argument("--json", action="store_true", help="Output JSON format")

    # If no arguments are passed, launch interactive menu
    if len(sys.argv) == 1:
        interactive_menu()
        return

    args = parser.parse_args()

    if not args.subcommand:
        interactive_menu(json_output=getattr(args, "json", False))
        return

    if args.subcommand == "scan":
        data = ForensicScanner.scan(args.path)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"=== Forensic Scan: {data['target']} ===")
            print(f"AppleDouble Sidecars Found: {data['appledouble_count']}\n")
            for f in data.get("files", []):
                rel = os.path.relpath(f['path'], args.path)
                print(f"File: {rel}")
                print(f"  Sidecar Size: {f.get('size', '-')} bytes | MTime: {f.get('mtime', '-')}")
                px = f.get("parsed_xattrs", {})
                if "quarantine" in px:
                    q = px["quarantine"]
                    print(f"  Quarantine: App='{q.get('agent_app')}' | UTC={q.get('timestamp_utc')}")
                if "provenance" in px:
                    pr = px["provenance"]
                    print(f"  Provenance: UUID={pr.get('probable_uuid')} | Hex={pr.get('raw_hex')[:32]}...")
                if "avkit_thumbnail_id" in px:
                    print(f"  AVKit Thumbnail ID: {px['avkit_thumbnail_id']}")
                print()

    elif args.subcommand == "inspect":
        target = Path(args.file)
        # If target is AppleDouble (._*)
        if target.name.startswith("._"):
            p = AppleDoubleParser(target)
            summary = p.get_summary()
            paired_data_file = target.parent / target.name[2:]
            if paired_data_file.exists():
                summary["paired_data_file"] = str(paired_data_file)
                if ExifToolInspector.available():
                    summary["exif_metadata"] = ExifToolInspector.inspect(paired_data_file).get("metadata", {})
        else:
            # Target is regular data file
            summary = {"path": str(target), "size": target.stat().st_size if target.exists() else 0}
            paired_ad = target.parent / f"._{target.name}"
            if paired_ad.exists():
                ad_p = AppleDoubleParser(paired_ad)
                summary["appledouble_sidecar"] = ad_p.get_summary()
            if ExifToolInspector.available():
                summary["exif_metadata"] = ExifToolInspector.inspect(target).get("metadata", {})

        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"=== Forensic Deep Inspection: {args.file} ===")
            print(f"File: {summary.get('path', args.file)}")
            print(f"Size: {summary.get('size', '-')} bytes")
            if "valid" in summary:
                print(f"Valid AppleDouble: {summary.get('valid')}")
                print(f"Extended Attributes: {summary.get('xattr_names')}")
                print("\nParsed Attributes:")
                print(json.dumps(summary.get("parsed_xattrs", {}), indent=2))
            if "appledouble_sidecar" in summary:
                ad = summary["appledouble_sidecar"]
                print(f"\nPaired AppleDouble Sidecar: {ad.get('path')}")
                print(f"Sidecar Size: {ad.get('size')} bytes | Valid: {ad.get('valid')}")
                print(f"Extended Attributes: {ad.get('xattr_names')}")
                if ad.get("parsed_xattrs"):
                    print("Parsed Sidecar Attributes:")
                    print(json.dumps(ad.get("parsed_xattrs", {}), indent=2))
            if "exif_metadata" in summary and summary["exif_metadata"]:
                print("\nEmbedded EXIF/Media Metadata (via ExifTool):")
                print(json.dumps(summary["exif_metadata"], indent=2))

    elif args.subcommand == "correlate":
        res = HostCorrelator.correlate(args.volume)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"=== Host Correlation Report: {args.volume} ===")
            print(f"Correlation Score: {res['score']}")
            print("Matched Evidence:")
            for m in res['matches']:
                print(f"  [+] {m}")
            print("\nDetailed Evidence Data:")
            print(json.dumps(res['evidence'], indent=2))

    elif args.subcommand == "spotlight":
        res = SpotlightInspector.inspect(args.volume)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"=== Volume Spotlight Inspection: {args.volume} ===")
            print(f"Spotlight Configured: {res.get('spotlight_configured')}")
            print(f"Volume UUID: {res.get('volume_uuid')}")
            print(f"Creation Version: {res.get('creation_version')} ({res.get('creation_date')})")
            print(f"Modification Version: {res.get('modification_version')} ({res.get('modification_date')})")
            print(f"Store UUIDs: {res.get('store_uuids')}")
            if "fsevents_uuid" in res:
                print(f"FSEvents UUID: {res.get('fsevents_uuid')}")

    elif args.subcommand == "clean":
        res = ForensicScanner.clean_artifacts(args.path, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            status_str = "Preview (dry run)" if res["dry_run"] else "Deleted"
            print(f"=== Artifact Cleanup: {args.path} ({status_str}) ===")
            print(f"Artifacts Found: {res['count']}")
            for item in res["removed_files"]:
                print(f"  - {item}")
            if res["dry_run"] and res["count"] > 0:
                print("\nRun with --force to permanently delete these artifacts.")


if __name__ == "__main__":
    main()
