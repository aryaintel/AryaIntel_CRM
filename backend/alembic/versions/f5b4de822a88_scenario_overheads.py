"""scenario_overheads

Revision ID: f5b4de822a88
Revises: 0ef0adfd6223
Create Date: 2025-09-14 16:11:03.740073
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f5b4de822a88"
down_revision = "0ef0adfd6223"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Overhead kalemleri: fixed tutar veya gelir yüzdesi
    op.create_table(
        "scenario_overheads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scenario_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),            # 'fixed' | '%_revenue'
        sa.Column("amount", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.CheckConstraint("type IN ('fixed','%_revenue')", name="ck_overhead_type"),
    )
    op.create_index("ix_overheads_scenario_id", "scenario_overheads", ["scenario_id"], unique=False)
    op.create_index("ix_overheads_type", "scenario_overheads", ["type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_overheads_type", table_name="scenario_overheads")
    op.drop_index("ix_overheads_scenario_id", table_name="scenario_overheads")
    op.drop_table("scenario_overheads")
