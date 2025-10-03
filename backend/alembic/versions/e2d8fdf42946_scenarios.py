"""scenarios

Revision ID: e2d8fdf42946
Revises: 69f201db28d7
Create Date: 2025-09-14 15:35:24.732588
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e2d8fdf42946"
down_revision: Union[str, Sequence[str], None] = "69f201db28d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite'ta ALTER kısıtlı olduğu için, UNIQUE ve FK'yi tablo oluştururken veriyoruz.
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_case_id", sa.Integer, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("months", sa.Integer, nullable=False, server_default=sa.text("36")),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.ForeignKeyConstraint(
            ["business_case_id"], ["business_cases.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "business_case_id", "name", name="uq_scenarios_name_per_bc"
        ),
    )
    op.create_index(
        "ix_scenarios_business_case_id", "scenarios", ["business_case_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_scenarios_business_case_id", table_name="scenarios")
    op.drop_table("scenarios")