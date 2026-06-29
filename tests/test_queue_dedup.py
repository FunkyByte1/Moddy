"""Re-enqueuing the same install (e.g. a collection's Re-install) must not leave the old finished
job's row alongside the new run — enqueue drops a prior finished job for the same game + ref."""
import asyncio
import unittest

import _harness  # noqa: F401 — installs the fake decky
import download_queue as dq
from download_queue import Job, STATUS_DONE, STATUS_DOWNLOADING


async def _noop_run(job):
    return True


class EnqueueDedupTest(unittest.TestCase):
    def setUp(self):
        dq.shutdown()
        dq._jobs.clear()
        dq._order.clear()
        dq._queue = None
        dq._active_id = None

    def _seed(self, job_id, appid, ref, status):
        j = Job(job_id, appid, "Collection: x", ref, "nexus", _noop_run)
        j.status = status
        dq._jobs[job_id] = j
        dq._order.append(job_id)

    def test_drops_prior_finished_same_ref(self):
        self._seed(99, 1, "collection:x", STATUS_DONE)
        new_id = asyncio.run(dq.enqueue(1, "Collection: x", "collection:x", "nexus", _noop_run))
        self.assertNotIn(99, dq._jobs)        # stale "done" row gone
        self.assertIn(new_id, dq._jobs)       # only the new run remains
        self.assertNotIn(99, dq._order)

    def test_keeps_finished_job_for_a_different_ref(self):
        self._seed(99, 1, "collection:other", STATUS_DONE)
        asyncio.run(dq.enqueue(1, "Collection: x", "collection:x", "nexus", _noop_run))
        self.assertIn(99, dq._jobs)           # unrelated collection's row untouched

    def test_keeps_an_unfinished_job_same_ref(self):
        self._seed(99, 1, "collection:x", STATUS_DOWNLOADING)  # still in flight — must not be dropped
        asyncio.run(dq.enqueue(1, "Collection: x", "collection:x", "nexus", _noop_run))
        self.assertIn(99, dq._jobs)

    def test_keeps_finished_job_for_a_different_game(self):
        self._seed(99, 2, "collection:x", STATUS_DONE)  # same ref, other appid
        asyncio.run(dq.enqueue(1, "Collection: x", "collection:x", "nexus", _noop_run))
        self.assertIn(99, dq._jobs)


if __name__ == "__main__":
    unittest.main()
