"""scenario_product_months 

Revision ID: 0ef0adfd6223
Revises: 282a3d20dff2
Create Date: 2025-09-14 16:00:04.404837
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0ef0adfd6223"
down_revision = "282a3d20dff2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Aylık miktarlar — (product, year, month) benzersiz
    op.create_table(
        "scenario_product_months",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scenario_product_id", sa.Integer, nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column(
            "quantity",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_product_id"], ["scenario_products.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_spm_month_1_12"),
        sa.UniqueConstraint(
            "scenario_product_id", "year", "month", name="uq_spm_unique"
        ),
    )
    op.create_index(
        "ix_spm_product_year_month",
        "scenario_product_months",
        ["scenario_product_id", "year", "month"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_spm_product_year_month", table_name="scenario_product_months")
    op.drop_table("scenario_product_months")
