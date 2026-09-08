"""Удаление сайта больше не уносит с собой оплаченную подписку

Подписка привязывается к сайту (триал, посайтовая выдача админом), а связь
стояла с ON DELETE CASCADE. Из-за этого удаление сайта стирало и подписку:
пользователь терял оплаченный срок, а отметка «пробный период уже был»
обнулялась. Теперь ссылка обнуляется, а сама подписка остаётся.

Revision ID: 0005_sub_survives_site
Revises: 0004_custom_code_type
"""
from __future__ import annotations

from alembic import op

revision = "0005_sub_survives_site"
down_revision = "0004_custom_code_type"
branch_labels = None
depends_on = None

FK_NAME = "subscriptions_site_id_fkey"


def _recreate(ondelete: str) -> None:
    # batch_alter_table нужен для SQLite: там внешний ключ меняется только
    # пересозданием таблицы. Исходная связь создавалась без имени, поэтому
    # задаём соглашение об именах — иначе batch-режим не найдёт, что удалять.
    with op.batch_alter_table(
        "subscriptions",
        naming_convention={"fk": "%(table_name)s_%(column_0_name)s_fkey"},
    ) as batch:
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.create_foreign_key(FK_NAME, "sites", ["site_id"], ["id"], ondelete=ondelete)


def upgrade() -> None:
    _recreate("SET NULL")


def downgrade() -> None:
    _recreate("CASCADE")
