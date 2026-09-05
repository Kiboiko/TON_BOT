"""«Свой код» становится типом проекта, а не оплаченным блоком внутри сайта

Revision ID: 0004_custom_code_type
Revises: 0003_deploy_zone
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_custom_code_type"
down_revision = "0003_deploy_zone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # В Postgres enum — отдельный тип, значение добавляется отдельной командой.
    # В SQLite это VARCHAR, менять нечего.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE site_type_enum ADD VALUE IF NOT EXISTS 'custom_code'")

    # Разовая покупка блока отменена: доступ к своему коду даёт подписка,
    # поэтому флаг оплаты больше ничего не решает.
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("custom_code_paid")


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(
            sa.Column(
                "custom_code_paid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    # Значение enum в Postgres удалить нельзя без пересоздания типа —
    # оставляем, лишний вариант никому не мешает.
