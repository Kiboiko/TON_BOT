"""Отпечаток опубликованного содержимого сайта

Чтобы пользователь мог обновить опубликованный сайт, приложению нужно понимать,
что сайт правили после публикации. При публикации в published_hash пишется
отпечаток содержимого; расхождение с текущим означает неопубликованные правки.
У уже опубликованных сайтов колонка пустая — до следующей публикации изменения
определяются по времени правки.

Revision ID: 0007_site_published_hash
Revises: 0006_custom_code_paid
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_site_published_hash"
down_revision = "0006_custom_code_paid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(sa.Column("published_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("published_hash")
