"""Tile scheduler: two priority queues, worker pools pinned per core class, single-flight, cancellation.

Foreground (fg) tiles are what the user is looking at; background (bg) tiles are speculative prefetch. They never
share workers: fg workers run on the performance cores and take only fg jobs, bg workers run on the efficiency cores
and take only bg jobs (E3: efficiency cores mixed in slow the foreground). Each job renders one 512² tile on one
thread (tile-level parallelism; the tile kernels release the GIL).

Requests hold *tickets* on jobs. Identical requests share one job (single-flight); a fg request for a job still
queued as bg promotes it. A job is cancelled only when its last live ticket is gone: a client disconnects
(`release`), or a newer generation of the same session supersedes older work (`supersede`). Cancellation is
cooperative: the job's token is checked before dequeue and between render stages.

    sched = Scheduler(run_job, fg_workers=8, bg_workers=3)
    ticket = sched.submit(key, payload, session="s1", gen=4, priority="fg", order=dist)
    result = ticket.future.result()      # or await asyncio.wrap_future(ticket.future)
    sched.supersede("s1", 5)             # cancel s1's older work
"""
import heapq
import itertools
import threading
import time
from concurrent.futures import Future

import psutil

from demlab.cancel import Cancelled, CancelToken
from demlab.cpus import core_sets, pin_current_thread


class Job:
    __slots__ = ("key", "payload", "priority", "gen", "order", "token", "future", "tickets", "state", "queued_at",
                 "started_at", "finished_at", "seq")

    def __init__(self, key, payload, priority, gen, order, seq):
        self.key, self.payload, self.priority, self.gen, self.order, self.seq = key, payload, priority, gen, order, seq
        self.token = CancelToken()
        self.future = Future()
        self.tickets = []
        self.state = "queued"  # queued / running / done
        self.queued_at = time.perf_counter()
        self.started_at = self.finished_at = None


class Ticket:
    __slots__ = ("job", "session", "gen", "alive")

    def __init__(self, job, session, gen):
        self.job, self.session, self.gen, self.alive = job, session, gen, True

    @property
    def future(self):
        return self.job.future


class Scheduler:
    def __init__(self, run_job, fg_workers=8, bg_workers=3, fg_cpus=None, bg_cpus=None, bg_cap=256,
                 bg_min_free_gb=2.5, bg_shared=False, bg_yield=True):
        """run_job(job) -> result; it may raise Cancelled (call job.token.check(stage) between stages).
        bg_yield: a bg worker does not start a new job while any fg job is queued or running (foreground strictly
        first; a running bg job is not interrupted). bg_shared: put bg workers on the performance cores (E6 variant;
        implies yielding)."""
        p, e, _ = core_sets()
        self.fg_cpus = list(fg_cpus) if fg_cpus is not None else p
        self.bg_cpus = list(bg_cpus) if bg_cpus is not None else (p if bg_shared else (e or p))
        self.run_job, self.bg_cap, self.bg_min_free = run_job, bg_cap, bg_min_free_gb * 2**30
        self.bg_shared = bg_shared
        self.bg_yield = bg_yield or bg_shared
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._q = {"fg": [], "bg": []}
        self._jobs = {}            # key -> job not yet finished
        self._seq = itertools.count()
        self._stop = False
        self.counters = {"submitted": 0, "joined": 0, "promoted": 0, "completed": 0, "cancelled": 0, "failed": 0,
                         "dropped_backpressure": 0, "cancelled_at": {}}
        self.last_cancel_wall = 0.0  # time.time() of the last job cancellation (queued jobs: when cancelled)
        self.busy_s = {"fg": 0.0, "bg": 0.0}
        self._threads = []
        for pool, n, cpus in (("fg", fg_workers, self.fg_cpus), ("bg", bg_workers, self.bg_cpus)):
            for i in range(n):
                t = threading.Thread(target=self._worker, args=(pool, cpus), name=f"tile-{pool}-{i}", daemon=True)
                t.start()
                self._threads.append(t)

    # ---------------------------------------------------------------- submission
    def submit(self, key, payload, session="", gen=0, priority="fg", order=0.0):
        with self._cv:
            job = self._jobs.get(key)
            if job is None or job.token.cancelled:  # a cancelled job still finishing its stage is not joined
                job = Job(key, payload, priority, gen, order, next(self._seq))
                self._jobs[key] = job
                self._push(job)
                self.counters["submitted"] += 1
                if priority == "bg":
                    self._backpressure()
            else:
                self.counters["joined"] += 1
                if priority == "fg" and job.priority == "bg" and job.state == "queued":
                    job.priority = "fg"           # promote: the stale bg heap entry is skipped when popped
                    job.gen, job.order = max(job.gen, gen), order
                    self._push(job)
                    self.counters["promoted"] += 1
                elif job.state == "queued" and gen > job.gen and job.priority == priority:
                    job.gen = gen
                    self._push(job)               # re-rank as newest generation
            ticket = Ticket(job, session, gen)
            job.tickets.append(ticket)
            self._cv.notify_all()
            return ticket

    def _push(self, job):
        heapq.heappush(self._q[job.priority], (-job.gen, job.order, job.seq, job))

    def _backpressure(self):
        """Keep the bg queue at most bg_cap live jobs: drop the oldest generation, then the farthest."""
        live = [j for (_, _, _, j) in self._q["bg"] if j.state == "queued" and j.priority == "bg"]
        excess = len(set(map(id, live))) - self.bg_cap
        if excess > 0:
            for j in sorted(set(live), key=lambda j: (j.gen, -j.order))[:excess]:
                self._cancel_locked(j, "dropped")
                self.counters["dropped_backpressure"] += 1

    # ---------------------------------------------------------------- cancellation
    def release(self, ticket):
        """A waiter is gone (e.g. client disconnected). Cancels the job if no live ticket is left."""
        with self._cv:
            ticket.alive = False
            self._maybe_cancel(ticket.job)

    def supersede(self, session, gen):
        """Kill `session`'s tickets older than `gen`; jobs left without live tickets are cancelled."""
        n = 0
        with self._cv:
            for job in list(self._jobs.values()):
                hit = False
                for t in job.tickets:
                    if t.alive and t.session == session and t.gen < gen:
                        t.alive, hit = False, True
                if hit and self._maybe_cancel(job):
                    n += 1
        return n

    def cancel_priority(self, session, priority="bg"):
        """Cancel all of a session's live work of one priority (e.g. background when a zoom gesture starts)."""
        n = 0
        with self._cv:
            for job in list(self._jobs.values()):
                if job.priority != priority:
                    continue
                hit = False
                for t in job.tickets:
                    if t.alive and t.session == session:
                        t.alive, hit = False, True
                if hit and self._maybe_cancel(job):
                    n += 1
        return n

    def _maybe_cancel(self, job):
        if job.state != "done" and not any(t.alive for t in job.tickets):
            self._cancel_locked(job, "superseded")
            return True
        return False

    def _cancel_locked(self, job, why):
        job.token.cancel()
        if job.state == "queued":           # never ran: finish it here; the heap entry is skipped later
            job.state = "done"
            self._forget(job)
            self.counters["cancelled"] += 1
            self.last_cancel_wall = time.time()
            stage = f"queued ({why})"
            self.counters["cancelled_at"][stage] = self.counters["cancelled_at"].get(stage, 0) + 1
            if not job.future.done():
                job.future.set_exception(Cancelled(stage))

    def _forget(self, job):
        if self._jobs.get(job.key) is job:
            del self._jobs[job.key]

    # ---------------------------------------------------------------- workers
    def _next(self, pool):
        q = self._q[pool]
        while q:
            _, _, _, job = heapq.heappop(q)
            if job.state == "queued" and job.priority == pool and not job.token.cancelled:
                return job
        return None

    def _worker(self, pool, cpus):
        pin_current_thread(cpus)
        while True:
            with self._cv:
                while True:
                    if self._stop:
                        return
                    blocked = pool == "bg" and ((self.bg_yield and self._fg_active()) or self._low_memory())
                    job = None if blocked else self._next(pool)
                    if job is not None:
                        break
                    self._cv.wait(timeout=0.05 if blocked else 0.5)
                job.state = "running"
                job.started_at = time.perf_counter()
            try:
                result = self.run_job(job)
            except Cancelled as e:
                self._finish(job, pool, exc=e, kind="cancelled", stage=str(e) or job.token.stage)
            except BaseException as e:  # noqa: BLE001 - surfaced to the waiting request
                self._finish(job, pool, exc=e, kind="failed")
            else:
                self._finish(job, pool, result=result)

    def _finish(self, job, pool, result=None, exc=None, kind="completed", stage=""):
        with self._cv:
            job.state = "done"
            job.finished_at = time.perf_counter()
            self.busy_s[pool] += job.finished_at - job.started_at
            self._forget(job)
            self.counters[kind] += 1
            if kind == "cancelled":
                self.last_cancel_wall = time.time()
                self.counters["cancelled_at"][stage] = self.counters["cancelled_at"].get(stage, 0) + 1
            self._cv.notify_all()
        if exc is not None:
            job.future.set_exception(exc)
        else:
            job.future.set_result(result)

    def _fg_active(self):
        if any(j.state == "running" and j.priority == "fg" for j in self._jobs.values()):
            return True
        return any(j.state == "queued" and j.priority == "fg" for (_, _, _, j) in self._q["fg"])

    def _low_memory(self):
        return self.bg_min_free > 0 and psutil.virtual_memory().available < self.bg_min_free

    # ---------------------------------------------------------------- introspection
    def stats(self):
        with self._lock:
            qd = {p: len({id(j) for (_, _, _, j) in q if j.state == "queued" and j.priority == p})
                  for p, q in self._q.items()}
            running = {p: sum(1 for j in self._jobs.values() if j.state == "running" and j.priority == p)
                       for p in ("fg", "bg")}
            return {"queued": qd, "running": running, "busy_s": dict(self.busy_s),
                    "last_cancel_wall": self.last_cancel_wall,
                    "counters": {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.counters.items()},
                    "fg_cpus": self.fg_cpus, "bg_cpus": self.bg_cpus, "bg_shared": self.bg_shared,
                    "bg_yield": self.bg_yield,
                    "workers": {"fg": sum(t.name.startswith("tile-fg") for t in self._threads),
                                "bg": sum(t.name.startswith("tile-bg") for t in self._threads)}}

    def shutdown(self):
        with self._cv:
            self._stop = True
            for job in list(self._jobs.values()):
                self._cancel_locked(job, "shutdown")
            self._cv.notify_all()
        for t in self._threads:
            t.join(timeout=2)
