from pathlib import Path
import tempfile
import unittest

from backend.app.jobs import JobRepository, JobStatus
from backend.app.storage import open_database


class JobRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.connection = open_database(Path(self.temp_dir.name) / "jobs.sqlite3")
        self.jobs = JobRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temp_dir.cleanup()

    def test_idempotent_submission_returns_same_job(self) -> None:
        first, created = self.jobs.enqueue("document", {"name": "örnek"}, "req-1")
        second, second_created = self.jobs.enqueue("document", {"name": "örnek"}, "req-1")
        self.assertTrue(created)
        self.assertFalse(second_created)
        self.assertEqual(first.id, second.id)

    def test_idempotency_key_cannot_change_request(self) -> None:
        self.jobs.enqueue("document", {"name": "a"}, "req-1")
        with self.assertRaisesRegex(ValueError, "farklı istek"):
            self.jobs.enqueue("document", {"name": "b"}, "req-1")

    def test_invalid_transition_is_rejected_and_restart_is_conservative(self) -> None:
        job, _ = self.jobs.enqueue("video", {}, "req-1")
        with self.assertRaisesRegex(ValueError, "Geçersiz iş geçişi"):
            self.jobs.transition(job.id, JobStatus.COMPLETED)
        self.jobs.transition(job.id, JobStatus.PREPARING)
        self.jobs.transition(job.id, JobStatus.RUNNING)
        self.assertEqual(self.jobs.recover_after_restart(), 1)
        recovered = self.connection.execute(
            "SELECT status FROM jobs WHERE id=?", (job.id,)
        ).fetchone()[0]
        self.assertEqual(recovered, JobStatus.RECOVERY_REQUIRED)


if __name__ == "__main__":
    unittest.main()
