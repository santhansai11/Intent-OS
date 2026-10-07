"""Unit tests for the NLU layer."""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nlu.classifier import IntentClassifier
from nlu.entity_extractor import extract_entities, resolve_deadline


class TestClassifier(unittest.TestCase):
    def setUp(self):
        self.clf = IntentClassifier()

    def test_prepare_meeting(self):
        result = self.clf.classify("Prepare everything for my 4 PM meeting.")
        self.assertEqual(result["intent"], "prepare_meeting")

    def test_show_schedule(self):
        result = self.clf.classify("Show my schedule for today")
        self.assertEqual(result["intent"], "get_schedule")

    def test_send_message(self):
        result = self.clf.classify("Send a message to John")
        self.assertEqual(result["intent"], "send_message")

    def test_submit_assignment(self):
        result = self.clf.classify("Submit my assignment to the professor")
        self.assertEqual(result["intent"], "submit_assignment")

    def test_download(self):
        result = self.clf.classify("Download the lecture videos")
        self.assertEqual(result["intent"], "download_files")

    def test_unknown_garbage(self):
        result = self.clf.classify("zzz qqq xyzzy blorple")
        self.assertEqual(result["intent"], "unknown")


class TestEntityExtraction(unittest.TestCase):
    def test_time_12h(self):
        e = extract_entities("Prepare everything for my 4 PM meeting.")
        self.assertEqual(e["time"], "16:00")

    def test_time_24h(self):
        e = extract_entities("Remind me to call mom at 18:30")
        self.assertEqual(e["time"], "18:30")

    def test_recipient(self):
        e = extract_entities("Send a message to John about the report")
        self.assertEqual(e.get("recipient"), "John")

    def test_resolve_deadline_future(self):
        entities = {"time": "16:00"}
        dl = resolve_deadline(entities, now=datetime(2026, 1, 1, 10, 0))
        self.assertEqual((dl.hour, dl.minute), (16, 0))

    def test_resolve_deadline_next_day(self):
        entities = {"time": "09:00"}
        dl = resolve_deadline(entities, now=datetime(2026, 1, 1, 20, 0))
        self.assertEqual(dl.hour, 9)

    def test_no_time_no_deadline(self):
        self.assertIsNone(resolve_deadline({}))


if __name__ == "__main__":
    unittest.main()
