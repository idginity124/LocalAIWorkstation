import asyncio
import unittest

from backend.app.resources import GpuObservation, GpuResourceManager, ResourceState


class FixedObservation:
    def __init__(self, *observations: GpuObservation):
        self.observations = list(observations)

    async def observe(self) -> GpuObservation:
        return self.observations.pop(0)


def observation(used: int | None, *, external_known: bool = True) -> GpuObservation:
    return GpuObservation(used, 16 * 1024**3, "test-only injected observation", external_known)


class GpuResourceManagerTests(unittest.TestCase):
    def test_concurrent_worker_event_loops_cannot_share_gpu(self):
        import concurrent.futures
        class SlowProvider:
            async def observe(self):
                await asyncio.sleep(.03)
                return observation(0)
        manager = GpuResourceManager(SlowProvider())
        def acquire(name):
            try:
                return asyncio.run(manager.acquire(name, 1024))
            except RuntimeError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(acquire, ["llm", "comfyui"]))
        self.assertEqual(sum(item is not None for item in outcomes), 1)
        asyncio.run(manager.release_and_verify(next(item for item in outcomes if item)))

    def test_unknown_or_unaccounted_gpu_blocks_acquisition(self) -> None:
        manager = GpuResourceManager(FixedObservation(observation(None)))
        with self.assertRaisesRegex(RuntimeError, "doğrulanamadı"):
            asyncio.run(manager.acquire("job-1", 1024))
        self.assertEqual(manager.state, ResourceState.UNKNOWN)

        outside_unknown = GpuResourceManager(
            FixedObservation(observation(0, external_known=False))
        )
        with self.assertRaisesRegex(RuntimeError, "doğrulanamadı"):
            asyncio.run(outside_unknown.acquire("job-2", 1024))

    def test_only_one_lease_and_release_needs_memory_proof(self) -> None:
        manager = GpuResourceManager(FixedObservation(observation(0), observation(0)))
        lease = asyncio.run(manager.acquire("job-1", 1024))
        self.assertEqual(manager.state, ResourceState.RUNNING)
        with self.assertRaisesRegex(RuntimeError, "kullanıyor"):
            asyncio.run(manager.acquire("job-2", 1024))
        asyncio.run(manager.release_and_verify(lease))
        self.assertEqual(manager.state, ResourceState.IDLE)

    def test_release_without_free_memory_enters_recovery(self) -> None:
        manager = GpuResourceManager(
            FixedObservation(observation(0), observation(8 * 1024**3)),
            release_attempts=1,
        )
        lease = asyncio.run(manager.acquire("job-1", 1024))
        with self.assertRaisesRegex(RuntimeError, "başlangıç seviyesine"):
            asyncio.run(manager.release_and_verify(lease))
        self.assertEqual(manager.state, ResourceState.RECOVERY_REQUIRED)


if __name__ == "__main__":
    unittest.main()
