"""Tests for file management: search, read, organize, backup + entity extraction."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.intent import COMPLETED
from intent_kernel.kernel import IntentKernel
from intent_kernel.ipc.service_bus import ServiceError
from nlu.entity_extractor import extract_entities
from services.filesystem.service import FilesystemService


class FileServiceTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        # A "user folder" with mixed file types
        self.mixed = self.base / "mixed"
        self.mixed.mkdir()
        (self.mixed / "report.pdf").write_text("quarterly report body", encoding="utf-8")
        (self.mixed / "photo.jpg").write_bytes(b"\x00\x01\x02binary-image")
        (self.mixed / "notes.txt").write_text("line one\nline two\n", encoding="utf-8")
        (self.mixed / "song.mp3").write_bytes(b"\x00\x01audio")
        self.svc = FilesystemService(
            documents_dir_path=self.base / "documents",
            downloads_dir_path=self.base / "downloads",
            backups_dir_path=self.base / "backups",
            allowed_roots=[self.base],
        )

    def tearDown(self):
        self._tmp.cleanup()


class TestListAndSearch(FileServiceTestBase):
    def test_list_folder(self):
        out = self.svc.cap_list_folder({"path": str(self.mixed)})
        self.assertEqual(out["count"], 4)
        names = {f["name"] for f in out["files"]}
        self.assertEqual(names, {"report.pdf", "photo.jpg", "notes.txt", "song.mp3"})

    def test_list_folder_missing(self):
        with self.assertRaises(ServiceError):
            self.svc.cap_list_folder({"path": str(self.base / "nope")})

    def test_search_by_keyword(self):
        out = self.svc.cap_search_files({"root": str(self.base), "keyword": "report"})
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["matches"][0]["name"], "report.pdf")

    def test_access_outside_allowlist_denied(self):
        with self.assertRaises(ServiceError):
            self.svc.cap_list_folder({"path": "C:\\Windows\\System32"})


class TestReadFile(FileServiceTestBase):
    def test_read_text_file(self):
        out = self.svc.cap_read_file({"path": str(self.mixed / "notes.txt")})
        self.assertFalse(out["binary"])
        self.assertEqual(out["lines"], 2)
        self.assertIn("line one", out["content"])

    def test_read_binary_file(self):
        out = self.svc.cap_read_file({"path": str(self.mixed / "photo.jpg")})
        self.assertTrue(out["binary"])
        self.assertIsNone(out["content"])

    def test_read_relative_resolves_in_sandbox(self):
        docs = self.base / "documents"
        docs.mkdir(exist_ok=True)
        (docs / "agenda.txt").write_text("hello agenda", encoding="utf-8")
        out = self.svc.cap_read_file({"path": "agenda.txt"})
        self.assertEqual(out["content"], "hello agenda")


class TestOrganize(FileServiceTestBase):
    def test_organize_moves_by_category(self):
        out = self.svc.cap_organize_folder({"path": str(self.mixed)})
        self.assertEqual(out["count"], 4)
        self.assertEqual(out["folders"], ["Audio", "Docs", "Images"])
        self.assertFalse((self.mixed / "report.pdf").exists())
        self.assertTrue((self.mixed / "Docs" / "report.pdf").exists())
        self.assertTrue((self.mixed / "Images" / "photo.jpg").exists())
        self.assertTrue((self.mixed / "Audio" / "song.mp3").exists())
        self.assertTrue((self.mixed / "Docs" / "notes.txt").exists())

    def test_organize_skips_existing_destinations(self):
        (self.mixed / "Docs").mkdir()
        (self.mixed / "Docs" / "report.pdf").write_text("already there", encoding="utf-8")
        out = self.svc.cap_organize_folder({"path": str(self.mixed)})
        self.assertEqual(out["skipped"], ["report.pdf"])
        self.assertEqual(out["count"], 3)


class TestBackup(FileServiceTestBase):
    def test_backup_creates_timestamped_copy(self):
        out = self.svc.cap_backup_folder({"path": str(self.mixed)})
        self.assertEqual(out["files"], 4)
        self.assertTrue(Path(out["backup_path"]).exists())
        self.assertTrue((Path(out["backup_path"]) / "report.pdf").exists())


class TestFileEntities(unittest.TestCase):
    def test_known_folder(self):
        e = extract_entities("Organize my Downloads folder")
        self.assertTrue(e["folder"].endswith("Downloads"))

    def test_absolute_folder_path(self):
        e = extract_entities("Organize the folder C:\\Data\\Projects")
        self.assertEqual(e["folder"], "C:\\Data\\Projects")

    def test_file_path(self):
        e = extract_entities("Read C:\\Data\\Projects\\report.pdf")
        self.assertEqual(e["path"], "C:\\Data\\Projects\\report.pdf")
        self.assertEqual(e["file"], "report.pdf")

    def test_bare_filename(self):
        e = extract_entities("Read agenda.txt for me")
        self.assertEqual(e["file"], "agenda.txt")
        self.assertEqual(e["path"], "agenda.txt")


class TestKernelFileIntents(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["INTENTOS_ROOT"] = self._tmp.name
        self.mixed = Path(self._tmp.name) / "mixed"
        self.mixed.mkdir()
        (self.mixed / "report.pdf").write_text("body", encoding="utf-8")
        (self.mixed / "photo.jpg").write_bytes(b"\x00img")
        self.kernel = IntentKernel(strategy="deadline", persist=False)

    def tearDown(self):
        os.environ.pop("INTENTOS_ROOT", None)
        self._tmp.cleanup()

    def test_organize_intent_end_to_end(self):
        intent = self.kernel.submit_text(f"Organize the folder {self.mixed}")
        self.assertEqual(intent.intent_type, "organize_folder")
        self.kernel.run_all()
        self.assertEqual(intent.state, COMPLETED)
        out = intent.step_results["S2"]["result"]
        self.assertEqual(out["count"], 2)
        self.assertTrue((self.mixed / "Docs" / "report.pdf").exists())

    def test_backup_intent_end_to_end(self):
        intent = self.kernel.submit_text(f"Back up the folder {self.mixed}")
        self.assertEqual(intent.intent_type, "backup_folder")
        self.kernel.run_all()
        self.assertEqual(intent.state, COMPLETED)
        out = intent.step_results["S1"]["result"]
        self.assertEqual(out["files"], 2)
        self.assertTrue(Path(out["backup_path"]).exists())

    def test_read_intent_end_to_end(self):
        target = self.mixed / "notes.txt"
        target.write_text("hello from notes", encoding="utf-8")
        intent = self.kernel.submit_text(f"Read the file {target}")
        self.assertEqual(intent.intent_type, "read_file")
        self.kernel.run_all()
        self.assertEqual(intent.state, COMPLETED)
        self.assertIn("hello from notes", intent.step_results["S1"]["result"]["content"])
