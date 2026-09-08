"""
Small shared helper for running Alembic migrations from Python code.

Why this exists as its own module: `alembic.command.upgrade()` ultimately
calls `asyncio.run()` inside `migrations/env.py` (see the async template
Alembic itself generates). That means it can only be called from a place
that does NOT already have an asyncio event loop running -- calling it from
inside a FastAPI lifespan coroutine, for example, would raise
"RuntimeError: asyncio.run() cannot be called from a running event loop".

So every caller (verify_migration_schema.py, pipeline/init_data.py, and any
future one-off script) must call this from plain synchronous top-level code,
before entering any `asyncio.run(...)` of their own -- not from within one.
"""
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_upgrade_head(db_url: str) -> None:
    """Run `alembic upgrade head` against db_url. Must be called from
    synchronous code with no asyncio event loop already running."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # migrations/env.py reads DATABASE_URL from the environment -- keep
    # that as the single source of truth rather than passing the URL
    # through Alembic's own config plumbing a second way.
    os.environ["DATABASE_URL"] = db_url
    command.upgrade(cfg, "head")
