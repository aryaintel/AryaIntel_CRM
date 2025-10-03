from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c8b7a1b2c3d4"
down_revision = "f5b4de822a88"   # zincirin sende doğru olanı neyse onu bırak
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # tablo zaten varsa yeniden oluşturma
    if "scenario_boq_items" in inspector.get_table_names():
        return

    op.create_table(
        "scenario_boq_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scenario_id", sa.Integer, sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section", sa.String(50), nullable=True),
        sa.Column("item_name", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_cogs", sa.Numeric(18, 4), nullable=True),
        sa.Column("frequency", sa.String(20), nullable=False, server_default=sa.text("'once'")),
        sa.Column("start_year", sa.Integer, nullable=True),
        sa.Column("start_month", sa.Integer, nullable=True),
        sa.Column("months", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.CheckConstraint("start_month IS NULL OR (start_month BETWEEN 1 AND 12)", name="ck_boq_start_month_1_12"),
    )

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scenario_boq_items" in inspector.get_table_names():
        op.drop_table("scenario_boq_items")
