"""scenario_products

Revision ID: 282a3d20dff2
Revises: e2d8fdf42946
Create Date: 2025-09-14 15:52:49.909212
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "282a3d20dff2"
down_revision: Union[str, Sequence[str], None] = "e2d8fdf42946"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite'ta ALTER sınırlı; tüm kısıtları oluştururken veriyoruz
    op.create_table(
        "scenario_products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scenario_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_cogs", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),  # SQLite uyumlu
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_scenario_products_scenario_id",
        "scenario_products",
        ["scenario_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scenario_products_scenario_id", table_name="scenario_products")
    op.drop_table("scenario_products")
