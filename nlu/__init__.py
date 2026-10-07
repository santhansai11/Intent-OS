"""Natural Language Understanding: text -> structured intent."""
from __future__ import annotations

from .classifier import IntentClassifier, TRAINING_DATA
from .entity_extractor import extract_entities, resolve_deadline

__all__ = ["IntentClassifier", "TRAINING_DATA", "extract_entities", "resolve_deadline"]
