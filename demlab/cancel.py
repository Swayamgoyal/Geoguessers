"""Cooperative cancellation for tile jobs.

Python threads cannot be interrupted, so long work checks a token between stages (after each block read, before the
kernel, before encoding). A cancelled token makes `check()` raise `Cancelled`; the caller unwinds and drops the job.

    token = CancelToken()
    token.check()          # raises Cancelled once token.cancel() was called
"""
import threading


class Cancelled(Exception):
    """Raised by CancelToken.check() after cancel()."""


class CancelToken:
    __slots__ = ("_event", "stage")

    def __init__(self):
        self._event = threading.Event()
        self.stage = ""  # last stage reached, for the request log ("cancelled at stage")

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def check(self, stage=""):
        if stage:
            self.stage = stage
        if self._event.is_set():
            raise Cancelled(self.stage)


NEVER = CancelToken()  # a token nobody cancels, for callers without cancellation
