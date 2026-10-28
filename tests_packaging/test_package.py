"""Ensure user profiles and diagnostic assets cannot enter the install ZIP."""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.build_release import COMPONENT, FILES, ROOT, build_archive, package_files


class PackageTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / ".git").exists(), "Source archive has no Git index")
    def test_allowlist_matches_tracked_runtime_files(self):
        tracked = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z", "--", COMPONENT.as_posix()],
            encoding="utf-8",
        )
        self.assertEqual(
            set(tracked.rstrip("\0").split("\0")),
            {(COMPONENT / name).as_posix() for name in FILES},
            "Review runtime changes and update the explicit package allowlist",
        )

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="smartlock-package-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name in FILES:
            path = root / COMPONENT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic fixture\n")
        return root

    def test_archive_excludes_unlisted_runtime_and_user_files(self):
        root = self.fixture()
        for relative in ("devices.json", ".storage/auth", "user.db", "profile/Cookies",
                         "logs/debug.log", "reports/result.html", "brand/screenshot.png",
                         "translations/private.json", "extra.py"):
            path = root / COMPONENT / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic private fixture")
        image = root / "docs/images/a1-ultra-home-assistant.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"synthetic screenshot")
        archive = build_archive(root, root / "result.zip")
        with ZipFile(archive) as package:
            self.assertEqual(set(package.namelist()),
                             {(COMPONENT / name).as_posix() for name in FILES})
            self.assertTrue(all(package.read(name) == b"synthetic fixture\n"
                                for name in package.namelist()))
        self.assertTrue(archive.with_suffix(".zip.sha256").read_text().startswith(
            hashlib.sha256(archive.read_bytes()).hexdigest()))

    def test_missing_deliverable_stops_packaging(self):
        root = self.fixture()
        (root / COMPONENT / "manifest.json").unlink()
        with self.assertRaises(ValueError):
            package_files(root)
        self.assertFalse((root / "result.zip").exists())

    def test_existing_archive_is_not_overwritten(self):
        root = self.fixture()
        archive = root / "result.zip"
        archive.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            build_archive(root, archive)
        self.assertEqual(archive.read_bytes(), b"existing archive")
