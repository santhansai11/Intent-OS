"""Tests for user-chosen destinations and output formats (PDF/DOCX/HTML/TXT)."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_kernel.paths import root
from nlu.entity_extractor import extract_entities
from services import _docgen
from services.filesystem.service import FilesystemService

MD = ("# Quantum Computing\n\nQuantum computers use **qubits** for computation.\n\n"
      "- superposition\n- entanglement\n\nSee the [wiki page]"
      "(https://en.wikipedia.org/wiki/Quantum_computing).")


class TestDocGen(unittest.TestCase):
    def test_pdf_is_valid_structure(self):
        payload, binary = _docgen.render(MD, ".pdf", "Quantum Computing")
        self.assertTrue(binary)
        self.assertTrue(payload.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Type /Catalog", payload)
        self.assertIn(b"/Type /Page", payload)
        self.assertTrue(payload.rstrip().endswith(b"%%EOF"))

    def test_pdf_wraps_long_text_multipage(self):
        long_text = "word " * 2000          # ~10k chars -> multiple pages
        payload, binary = _docgen.render("# T\n\n" + long_text, ".pdf", "T")
        self.assertTrue(binary)
        self.assertGreater(payload.count(b"/Type /Page"), 1)

    def test_docx_is_valid_zip_package(self):
        payload, binary = _docgen.render(MD, ".docx", "Quantum Computing")
        self.assertTrue(binary)
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = zf.namelist()
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("word/document.xml", names)
            doc = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("Quantum computers use qubits", doc)
            self.assertIn("<w:b/>", doc)          # bold heading run

    def test_html_and_txt(self):
        html, binary = _docgen.render(MD, ".html", "T")
        self.assertFalse(binary)
        self.assertIn("<h1>", html)
        self.assertIn('<a href="https://en.wikipedia.org/wiki/Quantum_computing">', html)
        txt, _ = _docgen.render(MD, ".txt", "T")
        self.assertNotIn("**", txt)
        self.assertIn("Quantum computers use qubits", txt)

    def test_md_passes_through(self):
        payload, binary = _docgen.render(MD, ".md", "T")
        self.assertFalse(binary)
        self.assertEqual(payload, MD)


class TestWriteFileFormats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.dest = self.base / "anywhere"          # outside the project dir
        self.dest.mkdir()
        self.svc = FilesystemService(
            documents_dir_path=self.base / "documents",
            downloads_dir_path=self.base / "downloads",
            backups_dir_path=self.base / "backups",
            workspace_dir_path=self.base / "workspace",
            allowed_roots=[self.base],
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_explicit_path_with_pdf_extension(self):
        out = self.svc.cap_write_file({
            "path": str(self.dest / "report.pdf"),
            "content": MD, "topic": "Quantum Computing",
        })
        self.assertEqual(out["format"], "PDF")
        self.assertEqual(Path(out["path"]), self.dest / "report.pdf")
        data = Path(out["path"]).read_bytes()
        self.assertTrue(data.startswith(b"%PDF-1.4"))

    def test_folder_destination_plus_format(self):
        out = self.svc.cap_write_file({
            "path": str(self.dest),                 # a folder
            "format": ".docx",
            "filename": "machine_learning_Summary",
            "content": MD, "topic": "Machine Learning",
        })
        self.assertTrue(out["path"].endswith(".docx"))
        with zipfile.ZipFile(out["path"]) as zf:
            self.assertIn("word/document.xml", zf.namelist())

    def test_format_overrides_wrong_extension(self):
        out = self.svc.cap_write_file({
            "path": str(self.dest / "summary.md"),
            "format": ".txt", "content": MD, "topic": "T",
        })
        self.assertTrue(out["path"].endswith(".txt"))
        self.assertEqual(out["format"], "TXT")
        self.assertNotIn("**", Path(out["path"]).read_text(encoding="utf-8"))

    def test_html_rendering(self):
        out = self.svc.cap_write_file({
            "path": str(self.dest / "page.html"),
            "content": MD, "topic": "T",
        })
        self.assertIn("<h1>", Path(out["path"]).read_text(encoding="utf-8"))


class TestSaveEntities(unittest.TestCase):
    def test_explicit_file_destination(self):
        e = extract_entities("Create a summary of machine learning "
                             "and save it to D:\\Docs\\ml-report.pdf")
        self.assertEqual(e["subject"], "machine learning")
        self.assertEqual(e["output_path"], "D:\\Docs\\ml-report.pdf")
        self.assertEqual(e["format"], ".pdf")

    def test_sentence_initial_save_with_folder(self):
        e = extract_entities("Save a summary of CPU scheduling in D:\\College")
        self.assertEqual(e["subject"], "CPU scheduling")
        self.assertEqual(e["output_path"], "D:\\College")

    def test_docx_destination(self):
        e = extract_entities("Explain Linux and store the brief in "
                             "C:\\Users\\me\\Documents\\linux.docx")
        self.assertEqual(e["subject"], "Linux")
        self.assertEqual(e["format"], ".docx")

    def test_plain_request_still_works(self):
        e = extract_entities("Write a brief summary of quantum computing")
        self.assertEqual(e["subject"], "quantum computing")
        self.assertIsNone(e.get("output_path"))


class TestSystemAccess(unittest.TestCase):
    """Default access is scoped; additional folders require explicit grants."""

    def setUp(self):
        self.svc = FilesystemService()

    def test_user_profile_not_implicitly_granted(self):
        from intent_kernel.ipc.service_bus import ServiceError
        with self.assertRaises(ServiceError):
            self.svc.cap_file_info({"path": str(Path.home())})

    def test_project_readable(self):
        out = self.svc.cap_file_info({"path": str(root())})
        self.assertTrue(out["is_dir"])

    def test_windows_dir_denied(self):
        from intent_kernel.ipc.service_bus import ServiceError
        with self.assertRaises(ServiceError):
            self.svc.cap_file_info({"path": "C:\\Windows\\System32"})
        with self.assertRaises(ServiceError):
            self.svc.cap_write_file({"path": "C:\\Windows\\Temp\\x.txt",
                                     "content": "nope"})

    def test_temp_dir_requires_explicit_grant(self):
        from intent_kernel.ipc.service_bus import ServiceError
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ServiceError):
                self.svc.cap_write_file({"path": str(Path(td) / "denied.txt"), "content": "no"})
            scoped = FilesystemService(allowed_roots=[td])
            out = scoped.cap_write_file({"path": str(Path(td) / "ok.txt"),
                                           "content": "hello world"})
            self.assertTrue(Path(out["path"]).exists())


if __name__ == "__main__":
    unittest.main()
