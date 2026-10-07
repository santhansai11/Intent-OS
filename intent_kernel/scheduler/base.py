"""Scheduler interface.

A scheduler receives the list of runnable (READY) intents and selects
which intent should receive execution time next.
"""
from __future__ import annotations

from typing import List, Optional

from ..intent import Intent


class SchedulerError(Exception):
    pass


class Scheduler:
    name = "base"

    def select(self, runnable: List[Intent]) -> Optional[Intent]:
        """Choose the next intent to run. Must not mutate the list."""
        raise NotImplementedError

    def describe(self) -> str:
        return self.__doc__ or self.name
