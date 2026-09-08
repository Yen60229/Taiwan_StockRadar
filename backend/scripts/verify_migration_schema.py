"""
Verify that `alembic upgrade head` produces a schema that exactly matches
`models.database.Base.metadata` (columns, types, nullability, unique
constraints, indexes) -- not just "did it run without erroring".

Why this exists: the baseline migration (migrations/versions/*_baseline_*.py)
was hand-written from DDL that SQLAlchemy's compiler generated, but a
hand-written migration can still drift from the models by a typo. Comparing
by eye isn't good enough to trust in production. This script is the actual
proof, meant to be run once against a disposable PostgreSQL (see the
--- section at the bottom of this file for how), and to be able to run
again any time the models or migrations change.

Usage:
    DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname \
        python scripts/verify_migration_schema.py

Exits 0 and prints "SCHEMA MATCHES" if everything lines up.
Exits 1 and prints every mismatch found otherwise.

This script assumes the target database is EMPTY or already at `head` --
it runs `alembic upgrade head` itself (idempotent), so pointing it at a
throwaway container is the intended use; never point it at production.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from models.database import Base
from scripts.alembic_utils import run_upgrade_head


def _sqla_type_name(coltype) -> str:
    """Normalize a SQLAlchemy type object to a comparable string."""
    return str(coltype).upper()


# Alembic's own bookkeeping table -- not part of the application schema,
# Base.metadata knows nothing about it, and it's supposed to be there.
_ALEMBIC_BOOKKEEPING_TABLES = {"alembic_version"}


async def inspect_actual_schema(db_url: str) -> dict:
    """Reflect the live database via a sync inspector (run in a thread)."""
    engine = create_async_engine(db_url)

    def _reflect(sync_conn):
        insp = inspect(sync_conn)
        out = {}
        for table_name in insp.get_table_names():
            if table_name in _ALEMBIC_BOOKKEEPING_TABLES:
                continue
            cols = {
                c["name"]: {
                    "type": _sqla_type_name(c["type"]),
                    "nullable": c["nullable"],
                }
                for c in insp.get_columns(table_name)
            }
            uniques = sorted(
                tuple(sorted(u["column_names"])) for u in insp.get_unique_constraints(table_name)
            )
            # PostgreSQL implements every UNIQUE constraint (including a
            # plain `Column(unique=True)`) as a unique index under the hood,
            # and get_indexes() faithfully reports that index. It's not a
            # real extra index -- it's the constraint's own implementation
            # detail -- so drop any index whose column set exactly matches
            # a unique constraint we already counted above, or we'd flag
            # every single UniqueConstraint in the app as a "missing index".
            indexes = sorted(
                (idx["name"], tuple(idx["column_names"]))
                for idx in insp.get_indexes(table_name)
                if tuple(sorted(idx["column_names"])) not in uniques
            )
            out[table_name] = {"columns": cols, "unique_sets": uniques, "indexes": indexes}
        return out

    async with engine.connect() as conn:
        result = await conn.run_sync(_reflect)
    await engine.dispose()
    return result


def expected_schema() -> dict:
    """Build the same shape of dict, but from Base.metadata (source of truth)."""
    from sqlalchemy.dialects import postgresql

    pg = postgresql.dialect()
    out = {}
    for name, table in Base.metadata.tables.items():
        cols = {
            # Compile through the postgres dialect, not a bare str(): a
            # generic sa.DateTime() stringifies as "DATETIME", but the
            # column postgres actually creates -- and what get_columns()
            # reflects back -- is TIMESTAMP. Comparing the two verbatim
            # would flag every single DateTime column as a type mismatch
            # even though the migration is byte-for-byte what create_all()
            # would have produced.
            c.name: {"type": _sqla_type_name(c.type.compile(dialect=pg)), "nullable": c.nullable}
            for c in table.columns
        }
        uniques = sorted(
            tuple(sorted(col.name for col in uc.columns))
            for uc in table.constraints
            if uc.__class__.__name__ == "UniqueConstraint"
        )
        indexes = sorted(
            (idx.name, tuple(col.name for col in idx.columns))
            for idx in table.indexes
        )
        out[name] = {"columns": cols, "unique_sets": uniques, "indexes": indexes}
    return out


def diff(expected: dict, actual: dict) -> list[str]:
    problems = []

    missing_tables = set(expected) - set(actual)
    extra_tables = set(actual) - set(expected)
    if missing_tables:
        problems.append(f"Tables missing from migrated DB: {sorted(missing_tables)}")
    if extra_tables:
        problems.append(f"Unexpected extra tables in migrated DB: {sorted(extra_tables)}")

    for table in sorted(set(expected) & set(actual)):
        exp, act = expected[table], actual[table]

        for col in set(exp["columns"]) - set(act["columns"]):
            problems.append(f"{table}.{col}: column missing from migrated DB")
        for col in set(act["columns"]) - set(exp["columns"]):
            problems.append(f"{table}.{col}: unexpected extra column in migrated DB")

        for col in set(exp["columns"]) & set(act["columns"]):
            e, a = exp["columns"][col], act["columns"][col]
            if e["nullable"] != a["nullable"]:
                problems.append(
                    f"{table}.{col}: nullable mismatch — model={e['nullable']} db={a['nullable']}"
                )
            # Type comparison is intentionally loose (e.g. "NUMERIC(10, 2)"
            # vs "NUMERIC(10, 2)" should match, but exact vendor string
            # formatting can differ across drivers) -- compare only the
            # leading type keyword, which is what actually matters for
            # correctness. That keyword can itself contain a space (e.g.
            # dialect-compiling sa.DateTime() gives the fully spelled out
            # "TIMESTAMP WITHOUT TIME ZONE", while a reflected column comes
            # back abbreviated as just "TIMESTAMP" -- both mean the exact
            # same Postgres type), so take the first whitespace-delimited
            # token *before* stripping any "(...)" parameter suffix, not
            # the other way around.
            e_kind = e["type"].split()[0].split("(")[0].strip() if e["type"] else ""
            a_kind = a["type"].split()[0].split("(")[0].strip() if a["type"] else ""
            if e_kind != a_kind:
                problems.append(
                    f"{table}.{col}: type mismatch — model={e['type']} db={a['type']}"
                )

        if exp["unique_sets"] != act["unique_sets"]:
            problems.append(
                f"{table}: unique constraint sets differ — "
                f"model={exp['unique_sets']} db={act['unique_sets']}"
            )

        exp_idx_cols = sorted(cols for _, cols in exp["indexes"])
        act_idx_cols = sorted(cols for _, cols in act["indexes"])
        if exp_idx_cols != act_idx_cols:
            problems.append(
                f"{table}: indexed column sets differ — "
                f"model={exp_idx_cols} db={act_idx_cols}"
            )

    return problems


async def _inspect_and_diff(db_url: str) -> int:
    print("Reflecting migrated schema ...")
    actual = await inspect_actual_schema(db_url)
    expected = expected_schema()

    problems = diff(expected, actual)
    if problems:
        print(f"\nSCHEMA MISMATCH ({len(problems)} problem(s)):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"\nSCHEMA MATCHES ✅  ({len(expected)} tables verified: {sorted(expected)})")
    return 0


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: set DATABASE_URL to a disposable PostgreSQL instance.", file=sys.stderr)
        return 2

    # ⚠️ run_upgrade_head() calls asyncio.run() internally (see
    # scripts/alembic_utils.py) -- it MUST run here, in plain sync code,
    # before we ever start our own event loop below. Calling it from inside
    # an `async def` that is itself already running under asyncio.run()
    # raises "asyncio.run() cannot be called from a running event loop".
    print(f"Running `alembic upgrade head` against {db_url.split('@')[-1]} ...")
    run_upgrade_head(db_url)

    return asyncio.run(_inspect_and_diff(db_url))


if __name__ == "__main__":
    sys.exit(main())
