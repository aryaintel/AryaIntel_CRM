# backend/alembic/versions/d560ce22ed65_add_boq_category_to_scenario_boq_items.py
"""Add BOQ category to scenario_boq_items"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d560ce22ed65"
down_revision: Union[str, Sequence[str], None] = "c8b7a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# PostgreSQL ENUM definition
boq_category_enum = postgresql.ENUM(
    "bulk_with_freight",
    "bulk_ex_freight",
    "freight",
    name="boq_category",
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # Create enum type if not exists
    boq_category_enum.create(bind=bind, checkfirst=True)

    # Add nullable column to keep backward-compat with existing rows
    op.add_column(
        "scenario_boq_items",
        sa.Column("category", boq_category_enum, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    # Drop column first (so enum is no longer referenced)
    op.drop_column("scenario_boq_items", "category")

    # Drop enum type if nothing else uses it
    boq_category_enum.drop(bind=bind, checkfirst=True)
