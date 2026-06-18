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
STATUS_NEEDS_INPUT = "needs_input"  # parked mid-install awaiting a user choice (e.g. a variant)
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
        self.run = run  # async callable run(job) -> bool | None | dict | str
        self.status = STATUS_QUEUED
        self.error = ""
        self.percent = 0
        self.sub_label = ""  # package currently downloading within this job
        self.items_done = 0  # packages started so far in this job's cascade (1-based "N")
        self.items_total = 0  # total packages this job will install ("M"); 0 = unknown
        self.cancel_requested = False
        # Parked-job (needs_input) support — used by the Nexus variant flow.
        self.variant: "str | None" = None      # the chosen variant, set on resume
        self.variants: list = []                # options to present while parked
        self.installed: list = []               # ids freshly installed this job (survives a park)
        self.rollback = None                    # optional async rollback(job) for a parked cancel
        self.cleanup = None                     # optional sync cleanup() (e.g. drop a cached extract)

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
            "variants": self.variants,
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


async def enqueue(appid: int, name: str, ref: str, kind: str, run, rollback=None, cleanup=None) -> int:
    """Register a job and hand it to the worker. Returns the new job_id immediately. `rollback`
    (async rollback(job)) and `cleanup` (sync) are invoked if a parked job is cancelled."""
    global _next_id
    _ensure_worker()
    job = Job(_next_id, appid, name, ref, kind, run)
    job.rollback = rollback
    job.cleanup = cleanup
    _next_id += 1
    _jobs[job.job_id] = job
    _order.append(job.job_id)
    assert _queue is not None
    _queue.put_nowait(job.job_id)
    await _emit_state()
    return job.job_id


async def cancel(job_id: int) -> bool:
    """Cancel a job. A running job is signalled through the shared install-cancel flag; a queued
    job is dropped before it starts; a parked (needs_input) job is rolled back here, since it's
    holding installed requirements + a cached archive but isn't downloading."""
    job = _jobs.get(job_id)
    if job is None or job.status in _FINISHED:
        return False
    job.cancel_requested = True
    if job_id == _active_id:
        # Downloading now: the cancel flag stops it, and install_nexus_mod's own rollback runs.
        utils.cancel_install()
    else:
        # Not downloading — queued, parked for input, or a just-resumed job waiting its turn. Tear
        # down anything it installed before it stopped (a no-op for a fresh / non-Nexus job, whose
        # `installed` is empty and rollback/cleanup hooks are None).
        await _discard_parked(job)
        job.status = STATUS_CANCELLED
        await _emit_state()
    return True


async def _discard_parked(job: Job) -> None:
    """Tear down a parked job that's being cancelled: roll back what it installed, drop its cache."""
    if job.rollback is not None:
        try:
            await job.rollback(job)
        except Exception as e:  # noqa: BLE001
            decky.logger.warning(f"Parked-job rollback failed for {job.name}: {e}")
    if job.cleanup is not None:
        try:
            job.cleanup()
        except Exception as e:  # noqa: BLE001
            decky.logger.warning(f"Parked-job cleanup failed for {job.name}: {e}")


async def resume(job_id: int, variant: str) -> bool:
    """Resume a parked job with the user's choice (e.g. a variant) — re-queue it; the worker
    re-runs it, reusing the cached archive so there's no second download."""
    job = _jobs.get(job_id)
    if job is None or job.status != STATUS_NEEDS_INPUT:
        return False
    job.variant = variant
    job.variants = []
    job.cancel_requested = False
    job.status = STATUS_QUEUED
    _ensure_worker()
    assert _queue is not None
    _queue.put_nowait(job_id)
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
    """Set how many packages the active job will install (the "M" in "N of M"). Resets the "N"
    counter, since this marks the start of a fresh counting pass (e.g. a resumed job re-resolves)."""
    if _active_id is None:
        return
    job = _jobs.get(_active_id)
    if job is None:
        return
    job.items_total = total
    job.items_done = 0
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
            # Result: None = cancelled mid-download, True = installed, False = failed. A dict with
            # needs_variant parks the job for a user choice (the install kept its cached archive);
            # a string is a handled error (e.g. "premium_required"). (A cancel that arrived too late
            # to stop a download that then succeeded is honestly a success — the mod is installed.)
            result = await job.run(job)
            # Honor a cancel the install couldn't observe: a resume installs from the cached archive
            # with no download to interrupt, so the cancel flag is never seen and the install
            # completes. If the user asked to cancel, tear down what was installed. (install_*_mod
            # already rolls back on None/False; this covers a True/parked result that slipped past a
            # late cancel. Only jobs with a rollback hook — Nexus — can undo here.)
            if job.cancel_requested and job.rollback is not None and (result is True or isinstance(result, dict)):
                await _discard_parked(job)
                result = None
            if isinstance(result, dict) and result.get("needs_variant"):
                job.variants = result.get("variants") or []
                job.status = STATUS_NEEDS_INPUT  # parked; worker moves on (does NOT block)
            elif isinstance(result, str):
                job.status = STATUS_FAILED
                job.error = "Nexus Premium account required" if result == "premium_required" else result
            elif result is None:
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
            if job.status != STATUS_NEEDS_INPUT:
                job.sub_label = ""
            await _emit_state()


def shutdown() -> None:
    """Cancel the worker task on plugin unload (best-effort)."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
    _worker_task = None
