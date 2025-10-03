"""calendar_months

Revision ID: 088a8782b6c0
Revises: f2d84974f547
Create Date: 2025-09-14 15:09:42.836087
"""
from typing import Sequence, Union
from datetime import date
from calendar import month_name

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "088a8782b6c0"
down_revision: Union[str, Sequence[str], None] = "f2d84974f547"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) tabloyu oluştur
    op.create_table(
        "calendar_months",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date_month", sa.Date, nullable=False, unique=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("year_month", sa.String(7), nullable=False),  # YYYY-MM
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("month_name", sa.String(12), nullable=False),
        sa.Column(
            "is_month_start",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("1"),  # SQLite uyumlu
        ),
    )
    op.create_index("idx_calendar_year_month", "calendar_months", ["year", "month"])

    # 2) seed 2000-01 .. 2100-12
    bind = op.get_bind()
    rows = []
    y, m = 2000, 1
    while (y, m) <= (2100, 12):
        d = date(y, m, 1)
        q = (m - 1) // 3 + 1
        rows.append(
            {
                "date_month": d,
                "year": y,
                "month": m,
                "year_month": f"{y:04d}-{m:02d}",
                "quarter": q,
                "month_name": month_name[m],
                "is_month_start": True,
            }
        )
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1

    if rows:
        bind.execute(
            sa.text(
                """
            INSERT INTO calendar_months
            (date_month, year, month, year_month, quarter, month_name, is_month_start)
            VALUES (:date_month, :year, :month, :year_month, :quarter, :month_name, :is_month_start)
            """
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index("idx_calendar_year_month", table_name="calendar_months")
    op.drop_table("calendar_months")
