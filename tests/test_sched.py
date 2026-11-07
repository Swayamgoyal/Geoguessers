"""Tile scheduler: priorities, single-flight, promotion, cancellation by generation and by release, backpressure,
cooperative cancel at stage boundaries.

    python -m pytest tests/test_sched.py -q
"""
import threading
import time

import pytest

from demlab.cancel import Cancelled
from demlab.sched import Scheduler


def make(run, fg=2, bg=1, **kw):
    return Scheduler(run, fg_workers=fg, bg_workers=bg, fg_cpus=[], bg_cpus=[], bg_min_free_gb=0, **kw)


def test_runs_and_returns_result():
    s = make(lambda job: job.payload * 2)
    try:
        assert s.submit("a", 21).future.result(timeout=5) == 42
        assert s.stats()["counters"]["completed"] == 1
    finally:
        s.shutdown()


def test_single_flight_joins_identical_keys():
    calls = []

    def run(job):
        calls.append(job.key)
        time.sleep(0.1)
        return job.key

    s = make(run, fg=4)
    try:
        tickets = [s.submit("k", None, session=f"s{i}") for i in range(20)]
        assert {t.future.result(timeout=5) for t in tickets} == {"k"}
        assert calls == ["k"] and s.stats()["counters"]["joined"] == 19
    finally:
        s.shutdown()


def test_newest_generation_and_nearest_first():
    order, gate = [], threading.Event()

    def run(job):
        gate.wait(5)
        order.append(job.key)

    s = make(run, fg=1, bg=0)
    try:
        s.submit("block", None, gen=0)               # occupies the only worker until the gate opens
        time.sleep(0.05)
        s.submit("old-far", None, gen=1, order=9)
        s.submit("new-far", None, gen=2, order=9)
        last = s.submit("new-near", None, gen=2, order=1)
        gate.set()
        last.future.result(timeout=5)
        time.sleep(0.2)
        assert order == ["block", "new-near", "new-far", "old-far"]
    finally:
        s.shutdown()


def test_fg_request_promotes_queued_bg_job():
    started = threading.Event()
    gate = threading.Event()

    def run(job):
        if job.key == "busy":
            started.set()
            gate.wait(5)
        return job.key

    s = make(run, fg=1, bg=1)
    try:
        s.submit("busy", None, priority="bg")       # occupies the only bg worker
        started.wait(5)
        s.submit("x", None, priority="bg")          # queued behind it as background
        t = s.submit("x", None, priority="fg")      # foreground request promotes it to the idle fg worker
        assert t.future.result(timeout=2) == "x"
        assert s.stats()["counters"]["promoted"] == 1
        gate.set()
    finally:
        s.shutdown()


def test_supersede_cancels_older_generations_only():
    gate = threading.Event()

    def run(job):
        gate.wait(5)
        return job.key

    s = make(run, fg=1, bg=0)
    try:
        s.submit("busy", None, session="other")
        time.sleep(0.05)
        old = s.submit("old", None, session="s", gen=1)
        shared = s.submit("shared", None, session="s", gen=1)
        s.submit("shared", None, session="other", gen=0)   # another session still needs "shared"
        new = s.submit("new", None, session="s", gen=2)
        assert s.supersede("s", 2) == 1                     # only "old" loses its last ticket
        with pytest.raises(Cancelled):
            old.future.result(timeout=2)
        gate.set()
        assert shared.future.result(timeout=5) == "shared" and new.future.result(timeout=5) == "new"
    finally:
        s.shutdown()


def test_release_cancels_running_job_at_next_stage():
    reached = threading.Event()
    stopped_at = []

    def run(job):
        reached.set()
        for stage in ("read", "kernel", "encode"):
            time.sleep(0.05)
            job.token.check(stage)
            stopped_at.append(stage)
        return "done"

    s = make(run, fg=1, bg=0)
    try:
        t = s.submit("k", None)
        reached.wait(5)
        s.release(t)
        with pytest.raises(Cancelled):
            t.future.result(timeout=5)
        assert stopped_at == []                              # stopped at the first stage boundary
        assert s.stats()["counters"]["cancelled_at"] == {"read": 1}
    finally:
        s.shutdown()


def test_background_never_runs_on_fg_workers_and_backpressure():
    seen = []
    gate = threading.Event()

    def run(job):
        seen.append((threading.current_thread().name, job.priority))
        gate.wait(5)

    s = make(run, fg=2, bg=1, bg_cap=5)
    try:
        for i in range(12):
            s.submit(f"b{i}", None, priority="bg", gen=i)
        time.sleep(0.2)
        st = s.stats()
        assert st["queued"]["bg"] <= 5 and st["counters"]["dropped_backpressure"] >= 6
        gate.set()
        time.sleep(0.3)
        assert all(name.startswith("tile-bg") for name, pr in seen if pr == "bg")
    finally:
        s.shutdown()


def test_cancel_priority_drops_session_background():
    gate = threading.Event()
    s = make(lambda job: gate.wait(5), fg=1, bg=1)
    try:
        s.submit("busy", None, session="s", priority="bg")
        time.sleep(0.05)
        queued = [s.submit(f"r{i}", None, session="s", priority="bg") for i in range(3)]
        assert s.cancel_priority("s", "bg") == 4
        for t in queued:
            with pytest.raises(Cancelled):
                t.future.result(timeout=2)
        gate.set()
    finally:
        s.shutdown()


def test_pool_cpu_time_placement_and_no_bg_workers():
    def run(job):
        t = time.thread_time()
        while time.thread_time() - t < 0.02:   # burn ~20 ms of CPU
            pass
        return 1

    s = make(run, fg=1, bg=1)
    try:
        s.submit("f", None, priority="fg").future.result(timeout=5)
        s.submit("b", None, priority="bg").future.result(timeout=5)
        st = s.stats()
        assert st["cpu_s"]["fg"] >= 0.015 and st["cpu_s"]["bg"] >= 0.015
        assert sum(st["ran_on"]["fg"].values()) == 1 and sum(st["ran_on"]["bg"].values()) == 1
        assert st["by_pool"]["fg"]["completed"] == 1 and st["by_pool"]["bg"]["completed"] == 1
        assert not s.bg_paused()
    finally:
        s.shutdown()
    s = make(run, fg=1, bg=0)
    try:
        assert s.bg_paused()      # no background workers: the server refuses prefetch instead of queueing it forever
    finally:
        s.shutdown()
