"""Lightweight intent classifier (TF-IDF + cosine similarity).

Implemented with the standard library only -- no external NLP
dependencies -- so the prototype runs anywhere Python 3.8+ runs. An
optional LLM backend can replace this later without changing the
kernel (the interface is `classify(text) -> {intent, confidence}`).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Training corpus: intent_type -> example utterances
# ---------------------------------------------------------------------------
TRAINING_DATA: Dict[str, List[str]] = {
    "prepare_meeting": [
        "prepare everything for my meeting",
        "prepare for the meeting",
        "get ready for my 4 pm meeting",
        "prepare everything i need for my meeting",
        "get my meeting ready",
        "meeting preparation",
        "prepare things for the meeting at 4",
    ],
    "collect_meeting_files": [
        "collect files for my compiler design meeting and save them in a folder",
        "gather all documents related to the meeting and copy them to my desktop",
        "save the files for my 4 pm meeting in the meeting folder",
    ],
    "get_schedule": [
        "show my schedule",
        "what is on my calendar today",
        "list my events",
        "my schedule for today",
        "what meetings do i have",
        "show my agenda",
    ],
    "send_message": [
        "send a message to john",
        "email my teammate the update",
        "send a text saying i am late",
        "message the team",
        "tell alice i will be late",
    ],
    "download_files": [
        "download the lecture videos",
        "download the files",
        "get the files from the course page",
        "fetch the pdfs",
        "download lecture notes",
    ],
    "set_reminder": [
        "remind me to call mom at 6",
        "set a reminder for the deadline",
        "remind me about the meeting",
        "create a reminder to submit the report",
    ],
    "submit_assignment": [
        "submit my assignment",
        "turn in the report",
        "send the assignment to the professor",
        "hand in my homework",
        "submit the assignment before midnight",
    ],
    "find_file": [
        "find my report",
        "find report.pdf in my documents folder",
        "locate the assignment file",
        "where is my notes file",
        "search for my project file",
        "find the file in my downloads folder",
    ],
    "read_file": [
        "read the file report.pdf",
        "read my notes file",
        "show me the contents of agenda.txt",
        "read the pdf",
        "what is inside my file",
        "show the file contents",
    ],
    "organize_folder": [
        "organize my downloads folder",
        "clean up my folder",
        "sort my files by type",
        "tidy my desktop folder",
        "organize the files in that folder",
    ],
    "backup_folder": [
        "back up my projects folder",
        "backup my documents folder",
        "make a backup of my folder",
        "save a copy of the folder",
        "create a backup of the directory",
    ],
    "create_summary": [
        "create a brief summary of quantum computing",
        "write a short summary of the topic",
        "summarize the article about operating systems",
        "make a brief summary of renewable energy",
        "give me a quick summary of machine learning",
        "prepare a one page summary of the report",
        "summarize this topic for me",
        "write a summary of the french revolution and save it as a file",
    ],
    "summarize_document": [
        "summarize my document", "summarize a document on my computer",
        "read my latest document and summarize it", "summarise the file",
        "make a summary of my notes file", "analyze my document and summarize it",
    ],
    "research_topic": [
        "research quantum computing",
        "find information about renewable energy",
        "look up the history of the internet",
        "gather notes on operating system scheduling",
        "investigate the topic of neural networks",
        "search the web for information about black holes",
        "do research on the topic of cryptography",
    ],
    "write_document": [
        "write a report about artificial intelligence",
        "draft a detailed document on climate change",
        "compose an essay about the industrial revolution",
        "create a detailed report on cyber security",
        "write a document about database indexing",
        "produce a study guide on data structures",
        "generate a research brief on quantum error correction",
    ],
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ---------------------------------------------------------------------------
# Rule pre-filter for content-generation intents.
#
# TF-IDF alone confuses "write a report about X" with "submit the report".
# These narrow, ordered rules give the generative intents a deterministic
# trigger; everything else still goes through the statistical classifier.
# ---------------------------------------------------------------------------
_DOC_NOUN = (r"(?:report|reports|essay|essays|article|articles|document|documents|"
             r"write[\s-]?up|whitepaper|study\s+guide|research\s+brief|"
             r"note|notes|overview|explanation|guide)")
_DOC_VERB = r"(?:write|create|draft|compose|generate|produce|make|prepare|build|put\s+together)"

CLASSIFICATION_RULES = [
    (re.compile(r"\b(?:meeting|class|lecture)\b[^.?!]*\b(?:files?|documents?|materials?|slides?)\b[^.?!]*\b(?:save|store|collect|gather|copy|put|organize|organise)\b|\b(?:save|store|collect|gather|copy)\b[^.?!]*\b(?:files?|documents?|materials?|slides?)\b[^.?!]*\b(?:meeting|class|lecture)\b", re.IGNORECASE),
     "collect_meeting_files", None),
    (re.compile(r"\b(?:summari[sz]e|summari[sz]ing|summary|analyse|analyze)\b(?:(?!\b(?:save|store|export)\b)[^.?!])*\b(?:(?:my|this|the)\s+[\w -]{0,30}\b(?:document|file|pdf|docx|report|notes?)\b|[\w.-]+\.(?:pdf|docx?|txt|md))", re.IGNORECASE),
     "summarize_document", None),
    # "summarize X" / "a brief summary of X" / "summaries on X"
    (re.compile(r"\b(summari[sz]e|summari[sz]ed|summaries|summary)\b", re.IGNORECASE),
     "create_summary", None),
    # "write a report about X" / "draft a detailed document on X"
    # (excluded when the user is really asking for a reminder or a message)
    (re.compile(rf"\b{_DOC_VERB}\b[^.?!]*?\b{_DOC_NOUN}\b", re.IGNORECASE),
     "write_document",
     re.compile(r"\b(remind|reminder|e-?mail|text|tweet|post)\b", re.IGNORECASE)),
    # "research X" / "look up X" / "search the web for X" / "gather notes on X"
    (re.compile(r"\b(research|look\s+up|investigate|gather)\b", re.IGNORECASE),
     "research_topic", None),
    (re.compile(r"\bsearch\s+(?:the\s+)?(?:web|internet|online)\b", re.IGNORECASE),
     "research_topic", None),
    (re.compile(r"\bfind\s+(?:information|info|articles)\s+about\b", re.IGNORECASE),
     "research_topic", None),
]


def rule_match(text: str):
    """Return (intent, pattern) when a deterministic rule fires, else (None, None)."""
    for pattern, intent, exclude in CLASSIFICATION_RULES:
        if exclude is not None and exclude.search(text):
            continue
        if pattern.search(text):
            return intent, pattern.pattern
    return None, None


def _tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


class IntentClassifier:
    """Max-similarity TF-IDF classifier over the training corpus."""

    def __init__(self, training: Dict[str, List[str]] = None):
        self.training = training or TRAINING_DATA
        docs: List[Tuple[str, Counter]] = []
        for intent_type, utterances in self.training.items():
            for utterance in utterances:
                docs.append((intent_type, Counter(_tokenize(utterance))))
        self._docs = docs
        self._idf = self._compute_idf(docs)

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_idf(docs: List[Tuple[str, Counter]]) -> Dict[str, float]:
        total_docs = len(docs)
        df: Counter = Counter()
        for _, tokens in docs:
            df.update(tokens.keys())
        return {
            term: math.log((total_docs + 1) / (count + 1)) + 1.0
            for term, count in df.items()
        }

    def _tfidf(self, tokens: List[str]) -> Counter:
        if not tokens:
            return Counter()
        counts = Counter(tokens)
        total = len(tokens)
        vec = Counter()
        for term, count in counts.items():
            vec[term] = (count / total) * self._idf.get(term, 1.0)
        return vec

    @staticmethod
    def _cosine(a: Counter, b: Counter) -> float:
        common = set(a) & set(b)
        num = sum(a[t] * b[t] for t in common)
        da = math.sqrt(sum(v * v for v in a.values())) or 1.0
        db = math.sqrt(sum(v * v for v in b.values())) or 1.0
        return num / (da * db)

    # ------------------------------------------------------------------
    def classify(self, text: str, threshold: float = 0.25) -> Dict:
        text = text or ""

        # 1) Deterministic rules win for generative intents (see above).
        ruled, pattern = rule_match(text)
        scores: Dict[str, float] = {}
        for intent_type, doc_vec in self._docs:
            sim = self._cosine(self._tfidf(_tokenize(text)), doc_vec)
            if sim > scores.get(intent_type, 0.0):
                scores[intent_type] = sim
        ordered = {k: round(v, 4) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])}

        if ruled:
            top = next(iter(ordered.values()), 0.0)
            return {
                "intent": ruled,
                "confidence": round(max(0.9, top), 4),
                "method": "rule",
                "matched": pattern,
                "scores": ordered,
            }

        # 2) Statistical fallback.
        if not scores:
            return {"intent": "unknown", "confidence": 0.0, "method": "tfidf", "scores": {}}
        best = max(scores, key=scores.get)
        confidence = scores[best]
        if confidence < threshold:
            return {"intent": "unknown", "confidence": round(confidence, 4),
                    "method": "tfidf", "scores": ordered}
        return {
            "intent": best,
            "confidence": round(confidence, 4),
            "method": "tfidf",
            "scores": ordered,
        }
