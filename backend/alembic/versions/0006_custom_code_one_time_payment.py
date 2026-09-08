"""«Свой код» снова покупается разово, а не открывается подпиской

Заказчик вернул схему из ТЗ: возможность своего кода стоит фиксированную сумму
за сайт (по умолчанию 5 GRAM), цену меняет админ в тарифах. Колонка
`custom_code_paid` возвращается — она была убрана миграцией 0004, когда доступ
давала подписка.

Существующие проекты «Свой код» отмечаются оплаченными: их владельцы уже
получили доступ по подписке, и отбирать его задним числом нельзя.

Revision ID: 0006_custom_code_paid
Revises: 0005_sub_survives_site
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_custom_code_paid"
down_revision = "0005_sub_survives_site"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.add_column(
            sa.Column(
                "custom_code_paid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute("UPDATE sites SET custom_code_paid = true WHERE type = 'custom_code'")


def downgrade() -> None:
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("custom_code_paid")
