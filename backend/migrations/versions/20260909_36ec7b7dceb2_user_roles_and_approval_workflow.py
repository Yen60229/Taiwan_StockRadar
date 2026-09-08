"""user roles and approval workflow

Adds the columns behind "registration needs my approval" + "I'm an admin":
role / status / approved_at / approved_by / last_login_at.

⚠️ The `status` column defaults to 'pending', which means **any user row
that already exists would become unable to log in the moment this runs**.
So the upgrade explicitly flips every pre-existing user to 'active' -- they
signed up back when registration was open and approval didn't exist, and
locking the site's own owner out of production would be a spectacular way
to ship this feature. New rows created *after* this migration still get
'pending' from the column default, which is exactly what we want.

Note on timestamps: these use naive DateTime to stay consistent with the
four DateTime columns already in this schema. Mixing naive and tz-aware
datetimes in one table raises TypeError the moment you compare them. The
roadmap (01-backend.md) has a separate task to move *all* of them to
timezone-aware `server_default=func.now()` in one sweep -- doing it to
only these new columns now would create exactly the mixed state that task
exists to avoid.

Revision ID: 36ec7b7dceb2
Revises: 0944c4e72b5a
Create Date: 2026-09-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '36ec7b7dceb2'
down_revision: Union[str, None] = '0944c4e72b5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(16),
                                     nullable=False, server_default="user"))
    op.add_column("users", sa.Column("status", sa.String(16),
                                     nullable=False, server_default="pending"))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                                     nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))

    op.create_foreign_key(
        "fk_users_approved_by", "users", "users",
        ["approved_by"], ["id"], ondelete="SET NULL",
    )

    # text + CHECK rather than a PG ENUM type: adding a value later is just
    # one constraint swap instead of ALTER TYPE (which has transaction
    # restrictions), while still refusing to store a garbage value.
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin')")
    op.create_check_constraint(
        "ck_users_status", "users",
        "status IN ('pending', 'active', 'rejected', 'disabled')",
    )

    # Everyone who registered before approval existed keeps their access.
    op.execute("UPDATE users SET status = 'active' WHERE status = 'pending'")


def downgrade() -> None:
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_constraint("fk_users_approved_by", "users", type_="foreignkey")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "approved_by")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "status")
    op.drop_column("users", "role")
