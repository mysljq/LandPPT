import pytest

from landppt.services.progress_tracker import ProgressInfo, ProgressTracker


def test_progress_percentage_counts_failed_and_skipped_slides():
    progress = ProgressInfo(
        task_id="task-1",
        project_id="project-1",
        total_slides=5,
        completed_slides=2,
        failed_slides=1,
        skipped_slides=1,
    )

    assert progress.processed_slides == 4
    assert progress.progress_percentage == 80


def test_progress_percentage_is_capped_by_total_slides():
    progress = ProgressInfo(
        task_id="task-2",
        project_id="project-2",
        total_slides=2,
        completed_slides=2,
        failed_slides=1,
        skipped_slides=1,
    )

    assert progress.processed_slides == 2
    assert progress.progress_percentage == 100


class FakeCache:
    is_connected = True

    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True


@pytest.mark.asyncio
async def test_async_progress_update_recovers_from_cache_when_local_state_is_missing():
    tracker = ProgressTracker()
    tracker._cache_service = FakeCache()

    await tracker.create_task_async("task-3", "project-3", 3)
    tracker._progress_data.clear()

    progress = await tracker.add_slide_completed_async("task-3", 0, "Intro")

    assert progress is not None
    assert progress.completed_slides == 1
    assert progress.progress_percentage == pytest.approx(100 / 3)
    assert tracker.get_progress("task-3") is progress
