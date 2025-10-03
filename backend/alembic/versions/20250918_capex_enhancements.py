"""capex v2: asset & depreciation fields"""

from alembic import op
import sqlalchemy as sa

# --- REVISION INFO ---
revision = "20250918_capex_enhancements"
down_revision = "20250917_add_scenario_capex"  # <-- DÜZELTME: önceki capex migration'a zincirle
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    insp = sa.inspect(bind)
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def _column_names(bind, table: str):
    insp = sa.inspect(bind)
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    has_tbl = _has_table(bind, "scenario_capex")

    # Tablo yoksa: tüm alanlarla oluştur
    if not has_tbl:
        op.create_table(
            "scenario_capex",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "scenario_id",
                sa.Integer(),
                sa.ForeignKey("scenarios.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2), nullable=False),
            sa.Column("notes", sa.String(), nullable=True),
            sa.CheckConstraint("month >= 1 AND month <= 12", name="ck_capex_month"),
            # --- NEW FIELDS (V2) ---
            sa.Column("asset_name", sa.String(), nullable=True),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("service_start_year", sa.Integer(), nullable=True),
            sa.Column("service_start_month", sa.Integer(), nullable=True),
            sa.Column("useful_life_months", sa.Integer(), nullable=True),
            sa.Column("depr_method", sa.String(), nullable=True, server_default=sa.text("'straight_line'")),
            sa.Column("salvage_value", sa.Numeric(18, 2), nullable=True, server_default=sa.text("0")),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("1")),
        )
        op.create_index(
            "ix_capex_scenario_year_month",
            "scenario_capex",
            ["scenario_id", "year", "month"],
            unique=False,
        )
        return

    # Tablo varsa: eksik sütunları ekle (SQLite uyumlu)
    cols = _column_names(bind, "scenario_capex")
    with op.batch_alter_table("scenario_capex") as batch:
        if "asset_name" not in cols:
            batch.add_column(sa.Column("asset_name", sa.String(), nullable=True))
        if "category" not in cols:
            batch.add_column(sa.Column("category", sa.String(), nullable=True))
        if "service_start_year" not in cols:
            batch.add_column(sa.Column("service_start_year", sa.Integer(), nullable=True))
        if "service_start_month" not in cols:
            batch.add_column(sa.Column("service_start_month", sa.Integer(), nullable=True))
        if "useful_life_months" not in cols:
            batch.add_column(sa.Column("useful_life_months", sa.Integer(), nullable=True))
        if "depr_method" not in cols:
            batch.add_column(sa.Column("depr_method", sa.String(), nullable=True, server_default=sa.text("'straight_line'")))
        if "salvage_value" not in cols:
            batch.add_column(sa.Column("salvage_value", sa.Numeric(18, 2), nullable=True, server_default=sa.text("0")))
        if "is_active" not in cols:
            batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("1")))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind, "scenario_capex"):
        return
    cols = _column_names(bind, "scenario_capex")
    to_drop = [
        "asset_name",
        "category",
        "service_start_year",
        "service_start_month",
        "useful_life_months",
        "depr_method",
        "salvage_value",
        "is_active",
    ]
    existing = [c for c in to_drop if c in cols]
    if not existing:
        return
    with op.batch_alter_table("scenario_capex") as batch:
        for c in existing:
            batch.drop_column(c)
