"""Create the system errors table.

Revision ID: 0003
Revises: 417c9a2fe32c
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "417c9a2fe32c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "errors",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_errors")),
    )


def downgrade() -> None:
    op.drop_table("errors")
