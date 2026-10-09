"""Filesystem service: document lookup, downloads and real file management."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from intent_kernel.ipc.service_bus import ServiceError
from intent_kernel.paths import backups_dir, documents_dir, downloads_dir, workspace_dir
from services.base_service import BaseService

_UNSAFE_NAME = re.compile(r"[^\w\s.\-()\[\]]+")

# OS-critical locations that are denied even when a drive is allowed.
# Resolved at import so case/symlink normalization matches _assert_allowed().
PROTECTED_PATHS = [
    Path(p).resolve() for p in (
        "C:/Windows", "C:/Program Files", "C:/Program Files (x86)",
        "C:/ProgramData", "C:/Users/Default",
    ) if Path(p).exists()
]


def safe_filename(name: str, default_ext: str = ".md") -> str:
    """Turn a topic/goal into a safe, human-readable filename."""
    cleaned = _UNSAFE_NAME.sub("", str(name or "")).strip(" .")
    cleaned = re.sub(r"\s+", "_", cleaned)
    if not cleaned:
        cleaned = "intent-output"
    if not Path(cleaned).suffix:
        cleaned += default_ext
    return cleaned[:120]


class FilesystemService(BaseService):
    """Sandboxed document service rooted at storage/documents."""

    name = "filesystem"
    description = "Document storage: search, read, write and download files"

    def __init__(self, documents_dir_path=None, downloads_dir_path=None,
                 backups_dir_path=None, workspace_dir_path=None,
                 allowed_roots=None, **kw):
        super().__init__(**kw)
        self.documents_dir = Path(documents_dir_path) if documents_dir_path else documents_dir()
        self.downloads_dir = Path(downloads_dir_path) if downloads_dir_path else downloads_dir()
        self.backups_dir = Path(backups_dir_path) if backups_dir_path else backups_dir()
        self.workspace_dir = Path(workspace_dir_path) if workspace_dir_path else workspace_dir()
        # Legacy demo service: default to project and ordinary document folders.
        # The real application uses the stricter per-intent CapabilityRegistry.
        if allowed_roots is None:
            env = os.environ.get("INTENTOS_ALLOWED_ROOTS")
            if env:
                allowed_roots = [s for s in re.split(r"[;,]", env) if s.strip()]
            else:
                from intent_kernel.paths import root
                allowed_roots = [root(), Path.home() / 'Documents',
                                 Path.home() / 'Downloads', Path.home() / 'Desktop']
        if allowed_roots is None:                       # pragma: no cover
            from intent_kernel.paths import root
            allowed_roots = [root(), Path.home()]
        self.allowed_roots = [Path(r).expanduser().resolve() for r in allowed_roots]

    # ------------------------------------------------------------------
    def _assert_allowed(self, resolved: Path) -> Path:
        """Enforce the allowlist on an already-resolved path.

        System-critical directories are always denied, even when inside an
        allowed root (defence in depth: e.g. C:\\Windows lives under C:\\).
        """
        for protected in PROTECTED_PATHS:
            try:
                resolved.relative_to(protected)
                raise ServiceError(
                    f"access denied: '{resolved}' is a protected system location "
                    f"({protected})"
                )
            except ServiceError:
                raise
            except ValueError:
                continue
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        raise ServiceError(
            f"access denied: '{resolved}' is outside the allowed roots "
            f"{[str(r) for r in self.allowed_roots]}"
        )

    def _resolve_allowed(self, raw_path) -> Path:
        """Resolve a path and enforce the allowlist (intent-level sandbox)."""
        if not raw_path:
            raise ServiceError("no path specified")
        p = Path(str(raw_path)).expanduser()
        if not p.is_absolute():
            p = self.documents_dir / p  # bare names resolve inside the sandbox
        return self._assert_allowed(p.resolve())

    # ------------------------------------------------------------------
    def _all_documents(self) -> List[Path]:
        return [p for p in sorted(self.documents_dir.rglob("*")) if p.is_file()]

    def cap_find_documents(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Find documents matching names/keywords from the calendar event."""
        related = params.get("related") or []
        if isinstance(related, str):
            related = [related]
        found = []
        for name in related:
            match = next((p for p in self._all_documents() if p.name == name), None)
            if match is None:
                stem = Path(name).stem.lower()
                match = next(
                    (p for p in self._all_documents() if stem in p.name.lower()), None
                )
            if match:
                found.append({"name": match.name, "path": str(match), "size": match.stat().st_size})
        # Also keyword scan when nothing matched (e.g. topic search)
        if not found:
            for p in self._all_documents():
                found.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
        return {"documents": found, "count": len(found)}

    def cap_download(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Simulate downloading course files into storage/downloads."""
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        files = ["lecture_01_notes.pdf", "lecture_02_slides.pptx"]
        saved = []
        for fname in files:
            target = self.downloads_dir / fname
            if not target.exists():
                target.write_text(f"Simulated download: {fname}\n", encoding="utf-8")
            saved.append({"name": fname, "path": str(target)})
        return {"downloaded": saved, "count": len(saved), "destination": str(self.downloads_dir)}

    # ------------------------------------------------------------------
    # Real file management (allowlist-enforced)
    # ------------------------------------------------------------------
    def cap_list_folder(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """List the files in a folder (name, size, type, modified time)."""
        path = self._resolve_allowed(params.get("path") or ".")
        if not path.exists():
            raise ServiceError(f"folder not found: {path}")
        if not path.is_dir():
            raise ServiceError(f"not a folder: {path}")
        files = []
        for entry in sorted(path.iterdir()):
            if entry.is_file():
                st = entry.stat()
                files.append({
                    "name": entry.name,
                    "size": st.st_size,
                    "ext": entry.suffix.lower() or "(none)",
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                })
        return {"path": str(path), "files": files, "count": len(files)}

    def cap_search_files(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Recursively search a folder for files matching a keyword."""
        root = self._resolve_allowed(params.get("root") or ".")
        keyword = str(params.get("keyword") or "").lower()
        if not root.exists():
            raise ServiceError(f"folder not found: {root}")
        matches, scanned = [], 0
        for p in root.rglob("*"):
            scanned += 1
            if scanned > 20000:  # traversal safety cap
                break
            if p.is_file() and (not keyword or keyword in p.name.lower()):
                matches.append({"name": p.name, "path": str(p), "size": p.stat().st_size})
                if len(matches) >= 50:
                    break
        return {"root": str(root), "keyword": keyword, "matches": matches, "count": len(matches)}

    def cap_read_file(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Read a text file's contents (binary files are detected, not dumped)."""
        raw = params.get("path")
        if not raw:
            raise ServiceError("no file specified (mention the file name or path)")
        path = self._resolve_allowed(raw)
        if not path.exists():
            raise ServiceError(f"file not found: {path}")
        if not path.is_file():
            raise ServiceError(f"not a file: {path}")
        st = path.stat()
        with open(path, "rb") as fh:
            binary = b"\x00" in fh.read(2048)
        if binary:
            return {"path": str(path), "name": path.name, "size": st.st_size,
                    "binary": True, "lines": 0, "preview": "(binary file - preview unavailable)",
                    "content": None}
        content = path.read_text(encoding="utf-8", errors="replace")[:200000]
        return {
            "path": str(path), "name": path.name, "size": st.st_size,
            "binary": False, "lines": len(content.splitlines()),
            "preview": content[:400], "content": content,
        }

    def cap_find_document_for_summary(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Find and extract a readable document when the user gives no path."""
        explicit = params.get("path") or params.get("file")
        candidates = []
        if explicit:
            candidates = [self._resolve_allowed(explicit)]
        else:
            roots = [self.documents_dir, self.workspace_dir, Path.home() / "Documents",
                     Path.home() / "Downloads", Path.home() / "Desktop"]
            seen = set()
            for root in roots:
                try:
                    root = self._assert_allowed(root.expanduser().resolve())
                    if not root.is_dir():
                        continue
                    for item in root.rglob("*"):
                        if not item.is_file() or item.suffix.lower() not in _READABLE_DOCUMENTS:
                            continue
                        resolved = item.resolve()
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        candidates.append(resolved)
                        if len(candidates) >= 500:
                            break
                except (OSError, ServiceError):
                    continue
        candidates = [p for p in candidates if p.is_file() and p.suffix.lower() in _READABLE_DOCUMENTS]
        if not candidates:
            raise ServiceError("I couldn't find a readable document in Documents, Downloads, Desktop, or IntentOS storage. Name the document or add it to one of those folders.")
        if not explicit and len(candidates) > 1:
            # Prefer a uniquely relevant filename; otherwise select the newest candidate.
            topic = str(params.get("topic") or "").lower()
            matched = [p for p in candidates if topic and topic in p.stem.lower()]
            if len(matched) == 1:
                candidates = matched
            else:
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        path = candidates[0]
        content = _extract_document_text(path)
        if not content.strip():
            raise ServiceError(f"'{path.name}' was found, but its text could not be extracted.")
        return {"path": str(path), "name": path.name, "content": content[:200000],
                "count": len(candidates), "status": f"selected {path.name}"}

    def cap_collect_meeting_files(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Copy calendar-linked or topic-matching files into a destination folder."""
        raw_destination = params.get("destination")
        if raw_destination:
            destination = self._resolve_allowed(raw_destination)
        else:
            topic = str(params.get("topic") or "meeting-materials")
            destination = self.workspace_dir / safe_filename(topic, default_ext="")
            destination = self._assert_allowed(destination.resolve())
        roots = [self.documents_dir, self.workspace_dir, Path.home() / "Documents",
                 Path.home() / "Downloads", Path.home() / "Desktop"]
        files: Dict[str, Path] = {}
        for root in roots:
            try:
                root = self._assert_allowed(root.expanduser().resolve())
                if not root.is_dir():
                    continue
                for index, item in enumerate(root.rglob("*")):
                    if index >= 5000:
                        break
                    try:
                        if item.is_file():
                            files[str(item.resolve()).casefold()] = item.resolve()
                            if len(files) >= 10000:
                                break
                    except OSError:
                        continue
            except (OSError, ServiceError):
                continue
        related = params.get("related") or []
        if isinstance(related, (str, dict)):
            related = [related]
        wanted = set()
        for item in related:
            name = item.get("name") if isinstance(item, dict) else str(item)
            if name:
                wanted.add(Path(name).name.casefold())
        selected = [p for p in files.values() if p.name.casefold() in wanted]
        topic = str(params.get("topic") or "").strip().lower()
        if not selected and topic:
            words = [w for w in re.findall(r"[a-z0-9]+", topic) if len(w) > 2]
            text_scans = 0
            for path in files.values():
                if any(word in path.stem.lower() for word in words):
                    selected.append(path)
                    continue
                if (text_scans < 100 and path.suffix.lower() in _READABLE_DOCUMENTS
                        and path.stat().st_size <= 2_000_000):
                    text_scans += 1
                    try:
                        body = _extract_document_text(path).lower()
                        if any(word in body for word in words):
                            selected.append(path)
                    except Exception:
                        continue
        if not selected:
            raise ServiceError("No files matched the meeting materials. Add meeting-related files to Documents, Downloads, Desktop, or IntentOS storage.")
        destination.mkdir(parents=True, exist_ok=True)
        copied, skipped = [], []
        for source in sorted(set(selected)):
            target = destination / source.name
            if target.exists():
                skipped.append(source.name)
                continue
            shutil.copy2(source, target)
            copied.append({"name": source.name, "source": str(source), "path": str(target)})
        return {"destination": str(destination), "files": copied, "count": len(copied),
                "skipped": skipped, "status": f"copied {len(copied)} meeting file(s)"}

    def cap_organize_folder(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Sort a folder's files into category subfolders (Docs, Images, ...)."""
        path = self._resolve_allowed(params.get("path") or self.documents_dir)
        if not path.is_dir():
            raise ServiceError(f"not a folder: {path}")
        moved, skipped = [], []
        for entry in sorted(path.iterdir()):
            if not entry.is_file():
                continue
            category = CATEGORY_MAP.get(entry.suffix.lower(), "Other")
            dest_dir = path / category
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / entry.name
            if dest.exists():
                skipped.append(entry.name)
                continue
            shutil.move(str(entry), str(dest))
            moved.append({"name": entry.name, "category": category,
                          "from": str(entry), "to": str(dest)})
        return {"path": str(path), "moved": moved, "count": len(moved),
                "skipped": skipped, "folders": sorted({m["category"] for m in moved})}

    def cap_backup_folder(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Create a timestamped copy of a folder under storage/backups/."""
        path = self._resolve_allowed(params.get("path") or "")
        if not path.is_dir():
            raise ServiceError(f"not a folder: {path}")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = self.backups_dir / f"{path.name or 'folder'}-{stamp}"
        shutil.copytree(str(path), str(dest))
        all_files = [p for p in dest.rglob("*") if p.is_file()]
        return {"source": str(path), "backup_path": str(dest), "files": len(all_files),
                "bytes": sum(p.stat().st_size for p in all_files), "status": "backup complete"}

    def cap_write_file(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Write generated text to a file, creating folders as needed (WRITE).

        The destination may be any path the user named in their request
        (resolved against the allowlist), and the requested format
        (.pdf/.docx/.html/.txt) is rendered from the Markdown content.
        """
        content = params.get("content")
        if content is None:
            raise ServiceError("no content supplied to write")
        content = str(content)
        if not content.strip():
            raise ServiceError("refusing to write an empty file")

        requested_format = (params.get("format") or "").strip() or None

        raw_path = params.get("path")
        if raw_path:
            path = self._resolve_allowed(raw_path)
            # "save it to D:\Docs" (a folder) -> derive the filename inside it.
            if path.suffix == "" or path.is_dir():
                name = safe_filename(params.get("filename") or params.get("name")
                                     or f"{params.get('topic') or 'intent-output'}"
                                     f"{requested_format or '.md'}")
                path = self._assert_allowed((path / name).resolve())
        else:
            name = safe_filename(params.get("filename") or params.get("name")
                                 or f"{params.get('topic') or 'intent-output'}"
                                 f"{requested_format or '.md'}")
            base = params.get("subfolder") or params.get("folder")
            if base:
                base = self._resolve_allowed(base)
            else:
                base = self.workspace_dir
            base.mkdir(parents=True, exist_ok=True)
            path = self._assert_allowed((Path(base) / name).resolve())

        # Honour an explicitly requested format by fixing the extension.
        if requested_format and not requested_format.startswith("."):
            requested_format = "." + requested_format
        if requested_format and path.suffix.lower() != requested_format.lower():
            path = path.with_suffix(requested_format)
        path = self._assert_allowed(path.resolve())

        # Render the requested document format from the Markdown content.
        from services import _docgen
        payload, is_binary = _docgen.render(
            content, path.suffix, title=Path(str(params.get("topic")
                                                  or params.get("filename")
                                                  or path.stem)).stem.replace("_", " "))

        existed = path.exists()
        if existed and not params.get("overwrite", True):
            raise ServiceError(f"file already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Guard against partial files on any failure.
        tmp = path.with_suffix(path.suffix + ".part")
        if is_binary:
            tmp.write_bytes(payload)
        else:
            tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

        from intent_kernel.paths import relative_to_root
        text_for_stats = content if is_binary else payload
        return {
            "path": str(path),
            "display_path": relative_to_root(path),
            "name": path.name,
            "folder": str(path.parent),
            "bytes": path.stat().st_size,
            "lines": str(text_for_stats).count("\n") + 1,
            "words": len(str(text_for_stats).split()),
            "format": path.suffix.lstrip(".").upper() or "TXT",
            "rendered_from": "markdown" if is_binary or path.suffix.lower()
            not in (".md",) else "plain",
            "created": not existed,
            "overwritten": existed,
            "preview": (content[:300] if is_binary
                        else str(payload)[:300]),
            "status": (("created" if not existed else "updated")
                       + f" {path.name} ({path.suffix.lstrip('.').upper() or 'TXT'})"),
        }

    def cap_file_info(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Report metadata for one file (size, type, modified time) (READ)."""
        path = self._resolve_allowed(params.get("path") or "")
        if not path.exists():
            raise ServiceError(f"file not found: {path}")
        st = path.stat()
        return {
            "path": str(path), "name": path.name, "is_dir": path.is_dir(),
            "bytes": st.st_size, "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "format": path.suffix.lstrip(".").upper() or "TXT",
            "status": "file inspected",
        }

    def cap_reveal(self, params: Dict[str, Any], intent=None) -> Dict[str, Any]:
        """Reveal a file or folder in the host GUI file manager (EXECUTE)."""
        path = self._resolve_allowed(params.get("path") or "")
        if not path.exists():
            raise ServiceError(f"path not found: {path}")
        try:
            if os.name == "nt":
                os.startfile(str(path))                       # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            raise ServiceError(f"could not open '{path}': {exc}") from exc
        return {"path": str(path), "opened": True, "status": f"opened {path.name}"}




# Extension -> target subfolder for the organizer
CATEGORY_MAP: Dict[str, str] = {
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images", ".gif": "Images",
    ".bmp": "Images", ".webp": "Images", ".svg": "Images",
    ".pdf": "Docs", ".doc": "Docs", ".docx": "Docs", ".txt": "Docs", ".md": "Docs",
    ".ppt": "Docs", ".pptx": "Docs", ".xls": "Docs", ".xlsx": "Docs", ".csv": "Docs",
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos", ".mov": "Videos",
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives", ".tar": "Archives",
    ".py": "Code", ".js": "Code", ".java": "Code", ".html": "Code", ".css": "Code",
    ".ipynb": "Code", ".json": "Code", ".exe": "Programs", ".msi": "Programs",
}

_READABLE_DOCUMENTS = {".txt", ".md", ".csv", ".html", ".htm", ".docx",
                       ".pptx", ".xlsx", ".xlsm", ".pdf"}


def _extract_document_text(path: Path) -> str:
    """Extract common document formats using the standard library."""
    suffix = path.suffix.lower()
    if suffix in {".docx", ".pptx", ".xlsx", ".xlsm"}:
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path) as archive:
            if suffix == ".docx":
                names = ["word/document.xml"]
            elif suffix == ".pptx":
                names = [n for n in archive.namelist()
                         if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            else:
                names = [n for n in archive.namelist()
                         if n == "xl/sharedStrings.xml" or
                         (n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))]
            parts = []
            for name in names:
                try:
                    root = ET.fromstring(archive.read(name))
                    parts.extend(t.text or "" for t in root.iter()
                                 if t.tag.endswith("}t") or t.tag.endswith("}v"))
                except (KeyError, ET.ParseError):
                    continue
        return "\n".join(parts)
    if suffix == ".pdf":
        if not path.read_bytes()[:5].startswith(b"%PDF-"):
            return path.read_text(encoding="utf-8", errors="replace")
        # Prefer standard PDF libraries when installed; retain a stdlib fallback.
        try:
            from pypdf import PdfReader
            extracted = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            if extracted.strip():
                return extracted
        except ImportError:
            pass
        try:
            import fitz
            with fitz.open(path) as doc:
                return "\n".join(page.get_text() for page in doc)
        except ImportError:
            pass
        # Handle simple PDFs with literal text strings; scanned/image PDFs need OCR.
        raw = path.read_bytes()[:20_000_000].decode("latin-1", errors="ignore")
        strings = re.findall(r"\(([^()]*(?:\\.[^()]*)*)\)\s*Tj", raw)
        return " ".join(re.sub(r"\\([()\\])", r"\1", s) for s in strings)
    return path.read_text(encoding="utf-8", errors="replace")
