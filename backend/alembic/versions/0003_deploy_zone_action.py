"""Тип действия администратора: разворот зоны субдоменов

Revision ID: 0003_deploy_zone
Revises: 0002_app_settings
"""
from __future__ import annotations

from alembic import op

revision = "0003_deploy_zone"
down_revision = "0002_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # В Postgres enum — отдельный тип, значение добавляется отдельной командой.
    # В SQLite это VARCHAR, менять нечего.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE admin_action_enum ADD VALUE IF NOT EXISTS 'deploy_zone'")


def downgrade() -> None:
    # Убрать значение из enum Postgres нельзя без пересоздания типа —
    # оставляем как есть, лишнее значение никому не мешает.
    pass
