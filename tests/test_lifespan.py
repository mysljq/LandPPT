import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

from dotenv import load_dotenv
import pytest

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
os.environ["DEBUG"] = "false"

from landppt import main as main_module


@pytest.mark.asyncio
async def test_lifespan_swallows_cancelled_error_and_runs_shutdown():
    startup = AsyncMock()
    shutdown = AsyncMock()

    with (
        patch.object(main_module, "startup_application", new=startup),
        patch.object(main_module, "shutdown_application", new=shutdown),
    ):
        context_manager = main_module.lifespan(main_module.app)
        await context_manager.__aenter__()
        suppressed = await context_manager.__aexit__(
            asyncio.CancelledError,
            asyncio.CancelledError(),
            None,
        )

    assert suppressed is True
    startup.assert_awaited_once()
    shutdown.assert_awaited_once()
