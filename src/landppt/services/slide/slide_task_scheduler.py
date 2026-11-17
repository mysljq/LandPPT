"""Bounded slide scheduling with dependencies released after persistence."""
import asyncio


async def stream_slide_tasks(requests, generate, concurrency, groups, is_cancelled):
    pending = dict(requests)
    requested = set(pending)
    dependencies = {
        page - 1: group["reference_page"] - 1
        for group in groups for page in group["pages"]
        if page != group["reference_page"]
    }
    completed = set()
    running = {}
    try:
        while pending or running:
            if await is_cancelled():
                yield None
                return
            for idx in list(pending):
                if len(running) >= max(1, concurrency):
                    break
                reference = dependencies.get(idx)
                if reference in requested and reference not in completed:
                    continue
                slide = pending.pop(idx)
                task = asyncio.create_task(generate(idx, slide))
                running[task] = idx
            if not running:
                raise ValueError("Slide reference dependencies cannot be resolved")
            done, _ = await asyncio.wait(
                running, timeout=0.25, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                idx = running.pop(task)
                yield task.result()
                # The caller saves the result before requesting the next item.
                completed.add(idx)
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
