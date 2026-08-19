#!/usr/bin/env python3
"""
Export all records from the global_template_suites table to a JSON file.

Usage:
    python export_global_template_suites.py [output.json]
    (default output: global_template_suites.json)
"""

import asyncio
import json
import os
import sys

# Add src to Python path (same as run.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Load environment variables
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


async def main(output_path: str) -> int:
    from landppt.services.template.global_template_suite_service import (
        GlobalTemplateSuiteService,
    )

    svc = GlobalTemplateSuiteService()
    try:
        suites = await svc.list_all_suites()
    finally:
        # list_all_suites 内部会关闭 session；这里显式兜底关闭连接池
        from landppt.database.database import async_engine

        if async_engine is not None:
            await async_engine.dispose()

    payload = {
        "exported_at": __import__("time").time(),
        "count": len(suites),
        "suites": suites,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(suites)} suites -> {output_path}")
    return 0


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "global_template_suites.json"
    # Windows: Proactor 事件循环保证兼容
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
    sys.exit(asyncio.run(main(out)))
