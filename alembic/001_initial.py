"""Initial: reflect existing database

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
    # 数据库已存在，无需执行 DDL
    # 执行 stamp 标记当前版本即可
    pass


def downgrade() -> None:
    pass
