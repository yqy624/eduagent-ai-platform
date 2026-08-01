"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.database import Base
    import app.models.models  # noqa: F401
    import app.models.ai_models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    inspector = sa.inspect(bind)
    if inspector.has_table("assignments"):
        columns = {column["name"] for column in inspector.get_columns("assignments")}
        if "detail" not in columns:
            op.add_column("assignments", sa.Column("detail", sa.Text(), nullable=True))

    if inspector.has_table("ai_runs"):
        columns = {column["name"] for column in inspector.get_columns("ai_runs")}
        if "plan_json" not in columns:
            op.add_column("ai_runs", sa.Column("plan_json", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
