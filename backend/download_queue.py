"""In-memory background download queue.

The plugin historically installed mods serially and blocking: the frontend awaited the
whole install (and its dependency cascade) and saw a single anonymous `install_progress`
percent. This module makes installs non-blocking from the UI's point of view — callers
enqueue a job and return immediately — while keeping the actual work **serial**: a single
worker drains one job at a time. Serial processing is deliberate; it sidesteps the temp-path
collisions and the single global cancel flag that the install code assumes.

A "job" is one top-level thing the user asked to install (e.g. "install Acme-Mod with its
dependencies"). Its dependency cascade runs inside the job; the package currently downloading
is surfaced as `sub_label`. Done/failed/cancelled jobs stay in the list until cleared so the
UI can show outcomes.

Two events drive the frontend store:
  - `queue_state`  : full snapshot (list of job dicts) — emitted on every structural change.
  - `queue_progress`: (job_id, percent, sub_label) — high-frequency, active job only.
"""

import asyncio
import decky

import utils

STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_FINISHED = {STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED}


class Job:
    def __init__(self, job_id: int, appid: int, name: str, ref: str, kind: str, run):
        self.job_id = job_id
        self.appid = appid
        self.name = name  # pretty display name
        self.ref = ref  # install id (full_name / mod_id) so the UI can match a card to its job
        self.kind = kind  # thunderstore | nexus | bmi
        self.run = run  # async callable () -> bool | None
        self.status = STATUS_QUEUED
        self.error = ""
        self.percent = 0
        self.sub_label = ""  # package currently downloading within this job
        self.items_done = 0  # packages started so far in this job's cascade (1-based "N")
        self.items_total = 0  # total packages this job will install ("M"); 0 = unknown
        self.cancel_requested = False

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "appid": self.appid,
            "name": self.name,
            "ref": self.ref,
            "kind": self.kind,
            "status": self.status,
            "error": self.error,
            "percent": self.percent,
            "sub_label": self.sub_label,
            "items_done": self.items_done,
            "items_total": self.items_total,
        }


_jobs: dict[int, Job] = {}
_order: list[int] = []  # job_ids in display order (queued → active → finished)
_queue: "asyncio.Queue[int] | None" = None
_worker_task: "asyncio.Task | None" = None
_active_id: int | None = None
_next_id = 1


def _ensure_worker() -> None:
    """Create the asyncio queue + worker lazily, on the running loop (set up at first enqueue)."""
    global _queue, _worker_task
    if _queue is None:
        _queue = asyncio.Queue()
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker())


def snapshot() -> list[dict]:
    return [_jobs[i].to_dict() for i in _order if i in _jobs]


async def _emit_state() -> None:
    await decky.emit("queue_state", snapshot())


async def enqueue(appid: int, name: str, ref: str, kind: str, run) -> int:
    """Register a job and hand it to the worker. Returns the new job_id immediately."""
    global _next_id
    _ensure_worker()
    job = Job(_next_id, appid, name, ref, kind, run)
    _next_id += 1
    _jobs[job.job_id] = job
    _order.append(job.job_id)
    assert _queue is not None
    _queue.put_nowait(job.job_id)
    await _emit_state()
    return job.job_id


async def cancel(job_id: int) -> bool:
    """Cancel a job. A queued job is dropped before it starts; the running job is signalled
    through the shared install-cancel flag (it's the only one downloading, so this is safe)."""
    job = _jobs.get(job_id)
    if job is None or job.status in _FINISHED:
        return False
    job.cancel_requested = True
    if job_id == _active_id:
        utils.cancel_install()
    else:
        # Not started yet: mark cancelled now; the worker skips it when it pops the id.
        job.status = STATUS_CANCELLED
        await _emit_state()
    return True


async def clear_finished() -> None:
    global _order
    for jid in [i for i in _order if _jobs.get(i) and _jobs[i].status in _FINISHED]:
        _jobs.pop(jid, None)
    _order = [i for i in _order if i in _jobs]
    await _emit_state()


async def clear_job(job_id: int) -> bool:
    """Dismiss a single finished (done/failed/cancelled) job from the list."""
    global _order
    job = _jobs.get(job_id)
    if job is None or job.status not in _FINISHED:
        return False
    _jobs.pop(job_id, None)
    _order = [i for i in _order if i in _jobs]
    await _emit_state()
    return True


# ── Hooks called from the install code path while a job is running ────────────────────────

async def report_progress(percent: int) -> None:
    """Per-chunk download progress for the active job (called from utils.download)."""
    if _active_id is None:
        return
    job = _jobs.get(_active_id)
    if job is None:
        return
    job.percent = percent
    await decky.emit("queue_progress", job.job_id, percent, job.sub_label)


async def set_sublabel(name: str) -> None:
    """Name the package whose archive is about to download, within the active job."""
    if _active_id is None:
        return
    job = _jobs.get(_active_id)
    if job is None or job.sub_label == name:
        return
    job.sub_label = name
    job.percent = 0
    await _emit_state()


async def note_total(total: int) -> None:
    """Set how many packages the active job will install (the "M" in "N of M")."""
    if _active_id is None:
        return
    job = _jobs.get(_active_id)
    if job is None:
        return
    job.items_total = total
    await _emit_state()


async def note_item(name: str) -> None:
    """Advance to the next package in the active job's cascade: name it and bump the counter."""
    if _active_id is None:
        return
    job = _jobs.get(_active_id)
    if job is None:
        return
    job.items_done += 1
    job.sub_label = name
    job.percent = 0
    await _emit_state()


async def _worker() -> None:
    global _active_id
    assert _queue is not None
    while True:
        job_id = await _queue.get()
        job = _jobs.get(job_id)
        if job is None:
            continue
        if job.cancel_requested:
            # Cancelled while still queued — status already set in cancel().
            continue
        _active_id = job_id
        job.status = STATUS_DOWNLOADING
        await _emit_state()
        try:
            # Trust the install result: None means it was cancelled mid-download, True installed,
            # False failed. (A cancel that arrived too late to stop a download that then succeeded
            # is honestly a success — the mod is installed.)
            result = await job.run()
            if result is None:
                job.status = STATUS_CANCELLED
            elif result:
                job.status = STATUS_DONE
                job.percent = 100
            else:
                job.status = STATUS_FAILED
                job.error = "Install failed"
        except Exception as e:  # noqa: BLE001 — a failed job must not kill the worker
            decky.logger.exception(f"Download job {job_id} ({job.name}) failed: {e}")
            job.status = STATUS_FAILED
            job.error = str(e)
        finally:
            _active_id = None
            job.sub_label = ""
            await _emit_state()


def shutdown() -> None:
    """Cancel the worker task on plugin unload (best-effort)."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None
