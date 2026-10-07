"""Entity extraction: times, days, recipients from natural language.

    "Prepare everything for my 4 PM meeting."
        -> {"time": "16:00", "day": "today"}
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

_TIME_12H = re.compile(r"\b(\d{1,2})(?::(\d{2})?)?\s*(a\.?m\.?|p\.?m\.?)", re.IGNORECASE)
_TIME_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_DAY_WORDS = {"today": "today", "tonight": "today", "tomorrow": "tomorrow"}
_RECIPIENT = re.compile(r"\b(?:to|for)\s+([A-Z][a-z]+)\b")
_TOPIC = re.compile(r"\b(?:about|regarding|for)\s+(?:my\s+)?([a-z][a-z ]{2,30}?)(?:\.|,|$)", re.IGNORECASE)

# --- content-generation entities -------------------------------------------
# "Write a brief summary of quantum computing"  -> topic = "quantum computing"
_CONTENT_VERB = r"(?:write|create|make|prepare|generate|produce|draft|compose|give\s+me|build)"
_CONTENT_NOUN = (
    r"(?:brief\s+|short\s+|detailed\s+|one[\s-]page\s+|quick\s+)?"
    r"(?:summary|summaries|report|reports|brief|briefs|essay|essays|note|notes|"
    r"article|articles|document|documents|overview|write[\s-]?up|whitepaper|"
    r"study\s+guide|research\s+brief|explanation)"
)
# "summary of/on/about X", "summary X", "summary for X"
_TOPIC_OF = re.compile(
    rf"\b{_CONTENT_NOUN}\s+(?:of|on|about|for|regarding|covering)\s+(.{{2,80}}?)\s*(?:[.,;!?]|$)",
    re.IGNORECASE,
)
# "summarize X", "explain X", "research X"
_TOPIC_VERB_OBJ = re.compile(
    r"\b(?:summari[sz]e|explain|research|investigate|describe|analyse|analyze|"
    r"document|write\s+about|tell\s+me\s+about)\s+(?:the\s+|a\s+|an\s+)?(.{2,80}?)\s*(?:[.,;!?]|$)",
    re.IGNORECASE,
)
# Fallback: "write a summary" + trailing noun phrase
_TOPIC_TRAILING = re.compile(
    rf"\b{_CONTENT_VERB}\b[^.]*?\b{_CONTENT_NOUN}\b[^.]*?\b(?:of|on|about|for)\s+(.{{2,80}}?)\s*(?:[.,;!?]|$)",
    re.IGNORECASE,
)
# Sentences that carry no topic at all
_TOPIC_STOPWORDS = {
    "", "it", "this", "that", "them", "me", "my notes", "my file", "the topic",
    "a topic", "something", "anything", "the file", "my document", "a summary",
    "the meeting", "my meeting", "summary", "notes", "help",
}

# Requested output length -> planner/renderer hint
_LENGTH_WORDS = {
    "brief": "brief", "short": "brief", "quick": "brief",
    "detailed": "detailed", "long": "detailed", "in-depth": "detailed",
    "comprehensive": "detailed", "deep": "detailed", "thorough": "detailed",
    "one-page": "medium", "one page": "medium",
    "medium": "medium",
}
_OUTPUT_FORMATS = {
    "pdf": ".pdf", "docx": ".docx", "doc": ".doc", "txt": ".txt", "text": ".txt",
    "md": ".md", "markdown": ".md", "html": ".html", "csv": ".csv", "json": ".json",
}
_WRITE_VERB = re.compile(r"\b(write|create|save|put|store|generate|make)\b", re.IGNORECASE)

# "… and save it to D:\Docs\ml.pdf" / "store the report in D:\Reports"
_SAVE_CLAUSE = re.compile(
    r"\s*(?:,?\s*(?:and|then)\s+|\s+|\b)?"          # leading joiner (optional:
    r"\b(?:save|store|export|put)\b\s+"              # sentence-initial "Save ..."
    r"(?:it|this|them|the\s+(?:\w+\s+){0,2})?\s*"
    r"(?:to|in|into|under|at)\s+"
    r"((?:[A-Za-z]:[\\/]|~/)[^\",;!?]*|[\w\-() ]+\.(?:pdf|docx|doc|txt|md|html|csv|json))\s*[.;!]?\s*$",
    re.IGNORECASE,
)
_SAVE_ABS_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|~/)[^\",;!?]*", re.IGNORECASE)
_SAVE_FILENAME = re.compile(r"\b[\w\-() ]+\.(?:pdf|docx|doc|txt|md|html|csv|json)\b", re.IGNORECASE)
# Anything that signals "produce some written content".
_CONTENT_TRIGGER = re.compile(
    rf"\b(?:{_CONTENT_VERB}|summari[sz]e|explain|research|investigate|describe|"
    rf"analyse|analyze|document|tell\s+me\s+about|summary|summaries|"
    rf"(?:save|store|export)\s+(?:an?\s+|the\s+|my\s+)?(?:brief\s+|short\s+|"
    rf"detailed\s+)?(?:summary|summaries|report|brief|essay|notes?|article|"
    rf"documents?|overview|whitepaper|study\s+guide))\b",
    re.IGNORECASE,
)
# Trailing destination inside a captured subject ("... in D:\College")
_TRAILING_DEST = re.compile(
    r"\s+(?:to|in|into|under|at)\s+"
    r"((?:[A-Za-z]:[\\/]|~/)[^,;!?]*|[A-Za-z]\s+drive|[\w\-() ]+\.(?:pdf|docx|doc|txt|md|html|csv|json))\s*$",
    re.IGNORECASE,
)


def _clean_topic(raw: str) -> Optional[str]:
    """Normalise a captured topic phrase; return None when it is not usable."""
    topic = re.sub(r"\s+", " ", (raw or "").strip(" .,;:!?\"'"))
    # Drop trailing lead-ins the regex may capture.
    topic = re.sub(r"^(?:(?:the|a|an|on|about|into|regarding)\s+)+", "", topic, flags=re.IGNORECASE).strip()
    topic = re.sub(r"\s+(?:and save it|and store it|to a file|into a file)$", "",
                   topic, flags=re.IGNORECASE).strip()
    # Drop a trailing destination path ("... in D:\College") the capture
    # may have swallowed when the save clause wraps the whole sentence.
    dest_m = _TRAILING_DEST.search(topic)
    if dest_m:
        topic = topic[: dest_m.start()].strip()
    # Drop trailing output-format / save instructions captured by the pattern.
    topic = re.sub(
        r"\s*(?:as|in|to|into)\s+(?:a\s+|an\s+)?(?:pdf|docx?|txt|text|md|markdown|html|csv|json)"
        r"(?:\s+(?:file|document|format))?\s*$", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\s+(?:and\s+)?(?:save|store)\s+it.*$", "", topic,
                   flags=re.IGNORECASE).strip(" .,;:!?\"'")
    topic = re.sub(r"\s+(?:and|then|also)\s+(?:write|save|store|create|put|generate|"
                   r"make|send|email)\b.*$", "", topic, flags=re.IGNORECASE).strip(" .,;:!?\"'")
    topic = re.sub(r"\s+(?:to|into|in|as)\s+(?:a\s+|an\s+|my\s+)?"
                   r"(?:file|folder|document|pdf|docx|txt|md|markdown)\b.*$", "",
                   topic, flags=re.IGNORECASE).strip(" .,;:!?\"'")
    if len(topic) < 2 or topic.lower() in _TOPIC_STOPWORDS:
        return None
    if _FILE_RE.fullmatch(topic):
        return None
    return topic

# --- file / folder entities -------------------------------------------------
_EXT = r"(?:pdf|docx?|pptx?|txt|md|csv|xlsx?|ipynb|zip|rar|7z|tar|jpg|jpeg|png|gif|bmp|svg|mp3|wav|flac|mp4|mkv|avi|mov|exe|msi|py|js|java|html|css|json|log|ini)"
_FILE_RE = re.compile(rf"((?:[A-Za-z]:[\\/])?[\w\-.]*?\.{_EXT})\b", re.IGNORECASE)
_FOLDER_PATH_RE = re.compile(r"([A-Za-z]:[\\/][\w \-.\\/]*)")
_KNOWN_FOLDER_RE = re.compile(
    r"\b(?:my |the )?(downloads?|documents?|desktop|pictures|videos|music)\s+folder\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"\"([^\"]+)\"")
KNOWN_FOLDERS = {
    "download": "Downloads", "downloads": "Downloads", "documents": "Documents",
    "desktop": "Desktop", "pictures": "Pictures", "videos": "Videos", "music": "Music",
}


def _normalize_time(hour: int, minute: int, meridiem: Optional[str]) -> Optional[str]:
    if meridiem:
        mer = meridiem.lower().replace(".", "").replace(" ", "")
        if mer == "am":
            if hour == 12:
                hour = 0
        elif mer == "pm":
            if hour != 12:
                hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def extract_entities(text: str) -> Dict[str, Any]:
    entities: Dict[str, Any] = {}
    text = text or ""

    # Time: prefer explicit am/pm, then 24h clock
    m = _TIME_12H.search(text)
    if m:
        hour, minute, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        t = _normalize_time(hour, minute, mer)
        if t:
            entities["time"] = t
    else:
        m = _TIME_24H.search(text)
        if m:
            t = _normalize_time(int(m.group(1)), int(m.group(2)), None)
            if t:
                entities["time"] = t

    # Day words
    for word, value in _DAY_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            entities["day"] = value
            break

    # Recipient ("send a message to John")
    m = _RECIPIENT.search(text)
    if m:
        entities["recipient"] = m.group(1)

    # Topic ("... about the physics assignment")
    m = _TOPIC.search(text)
    if m:
        topic = m.group(1).strip()
        if topic and topic.lower() not in ("me", "my", "it", "them"):
            entities["topic"] = topic

    meeting_topic = re.search(
        r"\b(?:meeting|class|lecture)\s+(?:on|about|for)\s+(.+?)"
        r"(?=\s+(?:at|on|tomorrow|today|and|save|store|collect|gather|copy)\b|[,;!?]|$)",
        text, re.IGNORECASE)
    if meeting_topic:
        entities["subject"] = _clean_topic(meeting_topic.group(1))
    else:
        possessive_topic = re.search(
            r"\b(?:my|the|a)\s+(.+?)\s+(?:meeting|class|lecture)\b",
            text, re.IGNORECASE)
        if possessive_topic:
            candidate = _clean_topic(possessive_topic.group(1))
            if candidate and not re.search(r"\b\d{1,2}(?::\d{2})?\b", candidate):
                entities["subject"] = candidate

    # ------------------------------------------------------------------
    # Files and folders
    # ------------------------------------------------------------------
    # Quoted path ("D:\My Files\report.pdf")
    m = _QUOTED.search(text)
    if m and any(sep in m.group(1) for sep in ("\\", "/")):
        entities["folder"] = m.group(1).strip()

    # Absolute path (with or without a file extension)
    m = _FOLDER_PATH_RE.search(text)
    if m:
        candidate = m.group(1).rstrip("\\/ ").strip()
        if re.search(rf"\.{_EXT}$", candidate, re.IGNORECASE):
            entities["path"] = candidate
            entities["file"] = Path(candidate).name
        elif "folder" not in entities:
            entities["folder"] = candidate

    # Known folder words ("organize my downloads folder")
    m = _KNOWN_FOLDER_RE.search(text)
    if m and "folder" not in entities:
        entities["folder"] = str(Path.home() / KNOWN_FOLDERS[m.group(1).lower()])

    # Bare file name with extension ("read agenda.txt")
    m = _FILE_RE.search(text)
    if m:
        name = m.group(1).strip()
        if "path" not in entities:
            entities["path"] = name
        if "file" not in entities:
            entities["file"] = Path(name).name

    # ------------------------------------------------------------------
    # Content generation: "write a brief summary of quantum computing"
    # ------------------------------------------------------------------
    # Explicit save destination ("… and save it to D:\Docs\ml.pdf") is
    # removed from the text BEFORE topic extraction so the path does not
    # pollute the subject.
    save_m = _SAVE_CLAUSE.search(text)
    if save_m:
        entities["save"] = True
        dest = save_m.group(1).strip().strip('"').rstrip(" .,;!?")
        pm = _SAVE_ABS_PATH.match(dest) or _SAVE_FILENAME.search(dest)
        if pm:
            entities["output_path"] = pm.group(0).strip()
            ext = Path(entities["output_path"]).suffix.lower()
            if ext in _OUTPUT_FORMATS.values():
                entities["format"] = ext
        topic_text = text[: save_m.start()]
    else:
        topic_text = text

    # "Save a summary of CPU scheduling in D:\College" -- the save clause
    # wraps the whole request, so also accept a trailing path-like
    # destination when a save verb is present.
    if "output_path" not in entities and \
            re.search(r"\b(?:save|store|export|put)\b", text, re.IGNORECASE):
        drive_dest = re.search(
            r"\b(?:to|in|into|under|at)\s+(?:the\s+)?([A-Za-z])\s+drive\b",
            text, re.IGNORECASE)
        if drive_dest:
            from intent_kernel.paths import workspace_dir
            project_root = Path(__file__).resolve().parents[1]
            drive = drive_dest.group(1).upper() + ":"
            if project_root.drive.upper() == drive:
                entities["output_path"] = str(workspace_dir())
            else:
                entities["output_path"] = str(Path(drive + "\\") / "IntentOS" / "workspace")
        dm = _TRAILING_DEST.search(text)
        if dm and "output_path" not in entities:
            dest = dm.group(1).strip().rstrip(" .,;!?")
            if dest and not dest.lower().startswith(("it ", "the file", "a file")):
                entities["output_path"] = dest
                ext = Path(dest).suffix.lower()
                if ext in _OUTPUT_FORMATS.values():
                    entities["format"] = ext

    # Resolve ordinary folder language without requiring a full path.
    dest_match = re.search(
        r"\b(?:save|store|export|put|copy|place)\b[^.?!]*?\b(?:to|in|into|under|at)\s+"
        r"(?:my|the)\s+(.+?)\s+(?:folder|directory)\b", text, re.IGNORECASE)
    if dest_match and "output_path" not in entities:
        raw_dest = re.sub(r"\s+", " ", dest_match.group(1)).strip(" .,/\\")
        first, _, tail = raw_dest.partition(" ")
        known = {name.lower(): name for name in ("Documents", "Downloads", "Desktop", "Pictures", "Videos", "Music")}
        if first.lower() in known:
            base = Path.home() / known[first.lower()]
            entities["output_path"] = str(base / tail) if tail else str(base)
        elif raw_dest:
            entities["output_path"] = str(Path.home() / "Documents" / raw_dest)

    # A short named destination such as "save the report to Research" is
    # interpreted as a folder beneath the user's Documents directory.
    if "output_path" not in entities:
        named_dest = re.search(
            r"\b(?:save|store|export|put|copy)\b[^.?!]*?\b(?:to|in|into|under|at)\s+"
            r"(?:my|the)?\s*([A-Za-z][\w -]{1,35}?)(?:\s+folder|\s+directory)?\s*$",
            text, re.IGNORECASE)
        if named_dest:
            dest = named_dest.group(1).strip()
            if dest.lower() not in {"a folder", "the folder", "a particular place", "somewhere"}:
                known = {"documents": "Documents", "downloads": "Downloads", "desktop": "Desktop"}
                entities["output_path"] = str(Path.home() / known.get(dest.lower(), "Documents") / ("" if dest.lower() in known else dest))

    if _CONTENT_TRIGGER.search(text):
        raw = None
        for pattern in (_TOPIC_OF, _TOPIC_VERB_OBJ, _TOPIC_TRAILING):
            m = pattern.search(topic_text) or pattern.search(text)
            if m:
                raw = m.group(1)
                break
        subject = _clean_topic(raw) if raw else None
        if subject:
            entities["subject"] = subject
        for word, level in _LENGTH_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                entities["length"] = level
                break
        m = re.search(r"\b(?:as|in|to|into)\s+(?:a\s+|an\s+)?"
                      r"(pdf|docx|doc|txt|text|md|markdown|html|csv|json)\b",
                      text, re.IGNORECASE)
        if m:
            entities["format"] = _OUTPUT_FORMATS.get(m.group(1).lower(), ".md")
        if re.search(r"\b(save|store|write)\s+(it|the\s+\w+)?\s*"
                     r"(to|in|into|as)\s+(a\s+)?(file|folder|document)\b",
                     text, re.IGNORECASE):
            entities["save"] = True

    if re.search(r"\b(?:save|store|export|put|copy)\b", text, re.IGNORECASE):
        entities.pop("recipient", None)

    return entities


def resolve_deadline(entities: Dict[str, Any], now: Optional[datetime] = None) -> Optional[datetime]:
    """Convert extracted entities into a concrete deadline datetime."""
    if not entities.get("time"):
        return None
    now = now or datetime.now()
    hour, minute = (int(x) for x in entities["time"].split(":"))
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now and entities.get("day") != "tomorrow":
        deadline += timedelta(days=1)
    if entities.get("day") == "tomorrow":
        deadline += timedelta(days=1)
    return deadline
