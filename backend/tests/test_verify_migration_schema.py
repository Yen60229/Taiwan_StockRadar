"""
Regression tests for scripts/verify_migration_schema.py's comparison logic
itself -- these run fully offline (no DB) because they only exercise
`expected_schema()` (pure Base.metadata introspection) and `diff()` (pure
dict comparison), not `inspect_actual_schema()` (needs a live connection).

Why this file exists: the first real run against Postgres on 2026-09-08
reported 11 "mismatches" that were all false positives in this comparison
code, not in the migration:
  - a generic sa.DateTime() renders as "DATETIME" via plain str(), but the
    column Postgres actually creates -- and what reflection reports back --
    is TIMESTAMP; comparing the two verbatim flags every DateTime column
  - Postgres backs every UNIQUE constraint (including plain
    Column(unique=True)) with an implicit unique index, which
    get_indexes() faithfully reports; treating that as an "extra index"
    flags every single UniqueConstraint in the app
  - alembic_version is Alembic's own bookkeeping table and was never
    supposed to be compared against Base.metadata in the first place
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

from scripts.verify_migration_schema import diff, expected_schema


class _Base(DeclarativeBase):
    pass


class _Widget(_Base):
    __tablename__ = "widgets"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=True)
    active = Column(Boolean, nullable=True)

    __table_args__ = (UniqueConstraint("id", "name", name="uq_widget_id_name"),)


def _expected():
    import scripts.verify_migration_schema as m
    original = m.Base
    m.Base = _Base
    try:
        return expected_schema()
    finally:
        m.Base = original


def _pg_reflection_spelling(type_name: str) -> str:
    """
    Real PostgreSQL reflection abbreviates some type names compared to
    what dialect-compiling the Python type object produces -- e.g.
    sa.DateTime().compile(dialect=postgresql.dialect()) spells out
    "TIMESTAMP WITHOUT TIME ZONE", but insp.get_columns() reports the same
    column back as plain "TIMESTAMP". Both are the exact same Postgres
    type; this reproduces that real-world abbreviation so the offline
    simulation below actually exercises the code path that broke twice
    in production (2026-09-08) instead of trivially matching itself.
    """
    if type_name.startswith("TIMESTAMP WITHOUT TIME ZONE"):
        return "TIMESTAMP" + type_name[len("TIMESTAMP WITHOUT TIME ZONE"):]
    return type_name


def _reflected_like(exp: dict) -> dict:
    """
    Build an "actual" dict shaped like what a real, CORRECT reflection of
    the migrated DB would return -- i.e. faithfully re-derive it from
    `exp` via the same rules real Postgres reflection actually applies
    (index-for-unique-constraint, abbreviated type spelling), rather than
    hand-copying `exp` verbatim (which would trivially always match and
    prove nothing about the comparison logic itself).
    """
    actual = {}
    for table, data in exp.items():
        uniques = data["unique_sets"]
        # Simulate raw get_indexes() output: what's explicitly declared,
        # PLUS the implicit index Postgres creates to back every unique
        # constraint -- this is the exact shape that caused the real
        # false-positive run on 2026-09-08.
        raw = list(data["indexes"]) + [
            (f"implicit_{table}_{i}", cols) for i, cols in enumerate(uniques)
        ]
        filtered = sorted(
            (name, cols) for name, cols in raw
            if tuple(sorted(cols)) not in uniques
        )
        actual[table] = {
            # dict(data["columns"]) alone only copies the outer dict --
            # the per-column {"type", "nullable"} dicts underneath would
            # still be the SAME objects as in `exp`, so mutating one of
            # them in a test (to simulate a real drift) would silently
            # corrupt `exp` too and the test would compare a dict against
            # itself. Copy each column's inner dict as well.
            "columns": {
                col: {**info, "type": _pg_reflection_spelling(info["type"])}
                for col, info in data["columns"].items()
            },
            "unique_sets": uniques,
            "indexes": filtered,
        }
    return actual


def test_datetime_column_does_not_falsely_mismatch():
    """
    Regression test for the exact false positive hit in production:
    `daily_quotes.created_at: type mismatch — model=DATETIME db=TIMESTAMP`.
    """
    exp = _expected()
    assert exp["widgets"]["columns"]["created_at"]["type"].startswith("TIMESTAMP"), (
        "expected_schema() must compile column types through the postgres "
        "dialect so a generic DateTime() renders as TIMESTAMP, matching "
        "what reflection actually reports -- not the bare 'DATETIME' that "
        "str(sa.DateTime()) produces"
    )

    actual = _reflected_like(exp)
    assert diff(exp, actual) == []


def test_unique_constraints_backing_index_is_not_a_false_positive():
    """
    Regression test: a UniqueConstraint's own implicit backing index
    (and a plain Column(unique=True)'s) must not be reported as an
    "unexpected extra index" when the schema is otherwise identical.
    """
    exp = _expected()
    actual = _reflected_like(exp)
    problems = diff(exp, actual)
    assert problems == [], f"false positives from a correct schema: {problems}"


def test_a_real_missing_column_is_still_caught():
    """The comparison must not have been made so lenient it stops catching
    an actual regression -- a genuinely dropped column must still fail."""
    exp = _expected()
    actual = _reflected_like(exp)
    del actual["widgets"]["columns"]["active"]

    problems = diff(exp, actual)
    assert any("active" in p and "missing" in p for p in problems)


def test_a_real_type_mismatch_is_still_caught():
    exp = _expected()
    actual = _reflected_like(exp)
    actual["widgets"]["columns"]["name"]["type"] = "INTEGER"

    problems = diff(exp, actual)
    assert any("name" in p and "type mismatch" in p for p in problems)


def test_a_real_missing_table_is_still_caught():
    exp = _expected()
    actual = _reflected_like(exp)
    del actual["widgets"]

    problems = diff(exp, actual)
    assert any("widgets" in p and "missing" in p for p in problems)
