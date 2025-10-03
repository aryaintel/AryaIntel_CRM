"""business_cases

Revision ID: 69f201db28d7
Revises: 088a8782b6c0
Create Date: 2025-09-14 15:24:19.176665
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "69f201db28d7"
down_revision: Union[str, Sequence[str], None] = "088a8782b6c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Eğer tablo yoksa: tabloyu, FK'yi ve UNIQUE constraint'i TEK seferde oluştur.
    if not insp.has_table("business_cases"):
        op.create_table(
            "business_cases",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("opportunity_id", sa.Integer, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.ForeignKeyConstraint(
                ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint(
                "opportunity_id", name="uq_business_cases_opportunity_id"
            ),
        )
        # Sorgu için normal (non-unique) index
        op.create_index(
            "ix_business_cases_opportunity_id",
            "business_cases",
            ["opportunity_id"],
            unique=False,
        )
    else:
        # Tablo bir önceki denemede oluştuysa (UNIQUE yoksa) UNIQUE INDEX ile zorunlu kıl.
        op.create_index(
            "uq_business_cases_opportunity_id",
            "business_cases",
            ["opportunity_id"],
            unique=True,
        )


def downgrade() -> None:
    # Tabloyu düşürmek, ilişkili index/constraint'leri de temizler.
    op.drop_table("business_cases")
