# C:/Dev/AryaIntel_CRM/backend/app/models/__init__.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    ForeignKey,
    UniqueConstraint,
    Index,
    CheckConstraint,
    func,
    Numeric,
    Boolean,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# =========================
# Core (Tenant / User / Role)
# =========================
class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role_name = Column(String, nullable=False, default="user")

    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uix_user_tenant_email"),)


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    permissions = Column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uix_role_tenant_name"),)


# =========================
# Indexing (CPI/Diesel vb.)
# =========================
class IndexSeries(Base):
    __tablename__ = "index_series"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    unit = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)

    points = relationship("IndexPoint", back_populates="series", cascade="all, delete-orphan", lazy="selectin")


class IndexPoint(Base):
    __tablename__ = "index_points"

    id = Column(Integer, primary_key=True, index=True)
    series_id = Column(Integer, ForeignKey("index_series.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1..12
    value = Column(Numeric(18, 6), nullable=False)

    series = relationship("IndexSeries", back_populates="points", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("series_id", "year", "month", name="uix_index_point_unique"),
        CheckConstraint("month >= 1 AND month <= 12", name="ck_index_month"),
        Index("ix_index_points_series", "series_id"),
    )


# =========================
# PRODUCTS (global, Salesforce benzeri)
# =========================
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    uom = Column(String, nullable=True)

    currency = Column(String(3), nullable=False, default="USD")
    base_price = Column(Numeric(18, 4), nullable=False, default=0)
    tax_rate_pct = Column(Numeric(9, 4), nullable=True)

    barcode_gtin = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    # DB'de kolon adı 'metadata' — ORM'de güvenli isim ile map'liyoruz
    meta_json = Column("metadata", Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)

    attributes = relationship("ProductAttribute", back_populates="product", cascade="all, delete-orphan", lazy="selectin")
    media = relationship("ProductMedia", back_populates="product", cascade="all, delete-orphan", lazy="selectin")
    price_entries = relationship("PriceBookEntry", back_populates="product", cascade="all, delete-orphan", lazy="selectin")
    # NEW: cost entries
    cost_entries = relationship("CostBookEntry", back_populates="product", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("code", name="uix_product_code"),
        Index("ix_products_active", "is_active"),
    )


class ProductAttribute(Base):
    __tablename__ = "product_attributes"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    value = Column(String, nullable=True)

    product = relationship("Product", back_populates="attributes", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uix_product_attr_unique"),
        Index("ix_product_attr_product", "product_id"),
    )


class ProductMedia(Base):
    __tablename__ = "product_media"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=True)     # image|pdf|spec|link
    url = Column(Text, nullable=False)
    title = Column(String, nullable=True)

    product = relationship("Product", back_populates="media", lazy="selectin")

    __table_args__ = (Index("ix_product_media_product", "product_id"),)


# =========================
# Price Terms (EXW/FOB/... snapshot + FK)
# =========================
class PriceTerm(Base):
    __tablename__ = "price_terms"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, unique=True)  # e.g., EXW, FOB
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    sort_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_price_terms_active", "is_active"),
    )


class PriceBook(Base):
    __tablename__ = "price_books"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True)  # seed & unique kullanım
    name = Column(String, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    is_default = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    entries = relationship("PriceBookEntry", back_populates="book", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("ix_price_books_active", "is_active"),
        Index("ix_price_books_default", "is_default"),
    )


class PriceBookEntry(Base):
    __tablename__ = "price_book_entries"

    id = Column(Integer, primary_key=True, index=True)
    price_book_id = Column(Integer, ForeignKey("price_books.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)

    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)

    list_price = Column(Numeric(18, 4), nullable=False, default=0)
    discount_pct = Column(Numeric(9, 4), nullable=True)

    # NEW (in DB): term snapshot + normalized FK
    price_term = Column(String, nullable=True)
    price_term_id = Column(Integer, ForeignKey("price_terms.id", ondelete="SET NULL"), nullable=True)

    book = relationship("PriceBook", back_populates="entries", lazy="selectin")
    product = relationship("Product", back_populates="price_entries", lazy="selectin")
    term = relationship("PriceTerm", lazy="selectin")

    __table_args__ = (
        Index("ix_pbe_book", "price_book_id"),
        Index("ix_pbe_product", "product_id"),
        # helpful resolver index (product + term + window)
        Index("ix_pbe_lookup", "product_id", "price_term_id", "valid_from", "valid_to"),
        # prevent inverted windows
        CheckConstraint("(valid_from IS NULL) OR (valid_to IS NULL) OR (valid_from <= valid_to)", name="ck_pbe_window"),
    )


# =========================
# Cost Books (mirrors Price Books, for unit costs)
# =========================
class CostBook(Base):
    __tablename__ = "cost_books"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    is_default = Column(Boolean, nullable=False, default=False, server_default="0")

    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    entries = relationship("CostBookEntry", back_populates="book", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("ix_cost_books_active", "is_active"),
        Index("ix_cost_books_default", "is_default"),
    )


class CostBookEntry(Base):
    __tablename__ = "cost_book_entries"

    id = Column(Integer, primary_key=True, index=True)
    cost_book_id = Column(Integer, ForeignKey("cost_books.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)

    valid_from = Column(Date, nullable=True)
    valid_to = Column(Date, nullable=True)

    unit_cost = Column(Numeric(18, 4), nullable=False)  # stored in book currency

    # snapshot + FK (optional), for parity with price terms
    cost_term = Column(String, nullable=True)
    cost_term_id = Column(Integer, ForeignKey("price_terms.id", ondelete="SET NULL"), nullable=True)

    notes = Column(Text, nullable=True)

    book = relationship("CostBook", back_populates="entries", lazy="selectin")
    product = relationship("Product", back_populates="cost_entries", lazy="selectin")
    term = relationship("PriceTerm", lazy="selectin")

    __table_args__ = (
        Index("ix_cbe_book", "cost_book_id"),
        Index("ix_cbe_product", "product_id"),
        # helpful resolver index (product + term + window)
        Index("ix_cbe_lookup", "product_id", "cost_term_id", "valid_from", "valid_to"),
        # prevent inverted windows
        CheckConstraint("(valid_from IS NULL) OR (valid_to IS NULL) OR (valid_from <= valid_to)", name="ck_cbe_window"),
    )


# =========================
# Product Formulations
# =========================
class ProductFormulation(Base):
    __tablename__ = "product_formulations"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=True)  # şimdilik opsiyonel
    code = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    base_price = Column(Numeric(18, 6), nullable=True)
    base_currency = Column(String(3), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    version_no = Column(Integer, nullable=False, default=1)
    locked_at = Column(DateTime, nullable=True)

    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)

    # lifecycle
    is_archived = Column(Boolean, nullable=False, default=False, server_default="0")
    archived_at = Column(DateTime, nullable=True)
    parent_formulation_id = Column(Integer, ForeignKey("product_formulations.id", ondelete="SET NULL"), nullable=True)

    components = relationship("FormulationComponent", back_populates="formulation",
                              cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("product_id", "code", name="uix_formulation_product_code"),
        Index("ix_formulation_product", "product_id"),
        Index("ix_formulation_active", "is_active"),
        Index("ix_formulation_archived", "is_archived"),
    )


class FormulationComponent(Base):
    __tablename__ = "formulation_components"

    id = Column(Integer, primary_key=True, index=True)
    formulation_id = Column(Integer, ForeignKey("product_formulations.id", ondelete="CASCADE"), nullable=False)
    index_series_id = Column(Integer, ForeignKey("index_series.id", ondelete="RESTRICT"), nullable=False)
    weight_pct = Column(Numeric(9, 4), nullable=False)                  # 0..100 toplam ~100
    base_index_value = Column(Numeric(18, 6), nullable=True)
    note = Column(Text, nullable=True)

    formulation = relationship("ProductFormulation", back_populates="components", lazy="selectin")
    index_series = relationship("IndexSeries", lazy="selectin")

    __table_args__ = (
        CheckConstraint("weight_pct >= 0", name="ck_form_comp_weight"),
        Index("ix_form_comp_formulation", "formulation_id"),
        Index("ix_form_comp_series", "index_series_id"),
    )


# =========================
# Escalation Policies (GLOBAL)
# =========================
class EscalationPolicy(Base):
    __tablename__ = "escalation_policies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    scope = Column(String(10), nullable=False, default="both")  # price|cost|both

    # rate-based (opsiyonel)
    rate_pct = Column(Numeric(9, 4), nullable=True)

    # index-based (opsiyonel)
    index_series_id = Column(Integer, ForeignKey("index_series.id", ondelete="RESTRICT"), nullable=True)

    # start period
    start_year = Column(Integer, nullable=False)
    start_month = Column(Integer, nullable=False)

    # caps/floors
    cap_pct = Column(Numeric(9, 4), nullable=True)
    floor_pct = Column(Numeric(9, 4), nullable=True)

    # schedule
    frequency = Column(String(10), nullable=True, default="annual")     # monthly|quarterly|annual
    compounding = Column(String(10), nullable=True, default="compound") # simple|compound

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    components = relationship("EscalationPolicyComponent", back_populates="policy",
                              cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint("start_month >= 1 AND start_month <= 12", name="ck_esc_start_month"),
        CheckConstraint("frequency IN ('monthly','quarterly','annual')", name="ck_esc_frequency"),
        CheckConstraint("compounding IN ('simple','compound')", name="ck_esc_compounding"),
        Index("ix_esc_index_series", "index_series_id"),
    )


class EscalationPolicyComponent(Base):
    __tablename__ = "escalation_policy_components"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("escalation_policies.id", ondelete="CASCADE"), nullable=False)
    index_series_id = Column(Integer, ForeignKey("index_series.id", ondelete="RESTRICT"), nullable=False)
    weight_pct = Column(Numeric(9, 4), nullable=False)
    base_index_value = Column(Numeric(18, 6), nullable=True)

    policy = relationship("EscalationPolicy", back_populates="components", lazy="selectin")
    index_series = relationship("IndexSeries", lazy="selectin")

    __table_args__ = (
        CheckConstraint("weight_pct >= 0", name="ck_esc_comp_weight"),
        Index("ix_esc_comp_policy", "policy_id"),
        Index("ix_esc_comp_series", "index_series_id"),
    )


# =========================
# Scenario-level Escalation Policies (NEW)
# =========================
class ScenarioEscalationPolicy(Base):
    __tablename__ = "scenario_escalation_policies"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    scope = Column(String(20), nullable=False, default="all")         # services|capex|all
    method = Column(String(20), nullable=False, default="fixed")      # fixed|index

    fixed_pct = Column(Numeric(8, 4), nullable=True)
    index_code = Column(String(50), nullable=True)

    base_year = Column(Integer, nullable=True)
    base_month = Column(Integer, nullable=True)

    step_per_month = Column(Integer, nullable=True)
    freq = Column(String(12), nullable=False, default="annual")

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("(base_month IS NULL) OR (base_month BETWEEN 1 AND 12)", name="ck_sesc_base_month"),
        CheckConstraint("freq IN ('annual','quarterly','monthly')", name="ck_sesc_freq"),
        CheckConstraint("method IN ('fixed','index')", name="ck_sesc_method"),
        CheckConstraint("scope IN ('services','capex','all')", name="ck_sesc_scope"),
        Index("ix_sesc_scenario", "scenario_id"),
        Index("ix_sesc_active", "is_active"),
    )


# =========================
# Scenario TWC (i.WC)
# =========================
class ScenarioTWC(Base):
    __tablename__ = "scenario_twc"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    dso_days = Column(Integer, nullable=False, default=45)
    dpo_days = Column(Integer, nullable=False, default=30)
    inventory_days = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)

    scenario = relationship("Scenario", back_populates="twc", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("scenario_id", name="uix_twc_scenario_unique"),
        Index("ix_twc_scenario", "scenario_id"),
        CheckConstraint("dso_days >= 0 AND dso_days <= 365", name="ck_twc_dso_days"),
        CheckConstraint("dpo_days >= 0 AND dpo_days <= 365", name="ck_twc_dpo_days"),
        CheckConstraint("(inventory_days IS NULL) OR (inventory_days >= 0 AND inventory_days <= 365)", name="ck_twc_inventory_days"),
    )


# =========================
# Accounts / Contacts
# =========================
class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    type = Column(String, nullable=True)
    website = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    billing_address = Column(Text, nullable=True)
    shipping_address = Column(Text, nullable=True)

    account_number = Column(String(50), nullable=True)
    employees = Column(Integer, nullable=True)
    annual_revenue = Column(Integer, nullable=True)
    rating = Column(String(20), nullable=True)
    ownership = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)

    # RESTRICT yerine SET NULL + NOT NULL çakışmasını çözmek için RESTRICT
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    owner = relationship("User", lazy="selectin")


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    # RESTRICT
    owner_id   = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    name  = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    title = Column(String, nullable=True)
    notes = Column(Text,   nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    account = relationship("Account", lazy="selectin")
    owner   = relationship("User", lazy="selectin")


# =========================
# Leads
# =========================
class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    # RESTRICT
    owner_id  = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    name    = Column(String, nullable=False)
    company = Column(String, nullable=True)
    email   = Column(String, nullable=True)
    phone   = Column(String, nullable=True)
    title   = Column(String, nullable=True)

    status  = Column(String, nullable=True)
    source  = Column(String, nullable=True)
    rating  = Column(String, nullable=True)
    notes   = Column(Text,   nullable=True)

    converted_account_id     = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    converted_opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
    converted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", lazy="selectin")
    converted_account = relationship("Account", lazy="selectin", foreign_keys=[converted_account_id])
    converted_opportunity = relationship("Opportunity", lazy="selectin", foreign_keys=[converted_opportunity_id])


# =========================
# Pipeline / Stage / Opportunity
# =========================
class Pipeline(Base):
    __tablename__ = "pipelines"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Stage(Base):
    __tablename__ = "stages"
    id = Column(Integer, primary_key=True, index=True)
    # FIX: tenant_id artık tenants.id'ye referans verir
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    pipeline_id = Column(Integer, ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False)

    name = Column(String, nullable=False)
    order_index = Column(Integer, nullable=False, default=1)
    win_probability = Column(Integer, nullable=True)

    created_at = Column(DateTime, server_default=func.now())


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    # RESTRICT
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    name = Column(String, nullable=False)
    amount = Column(Integer, nullable=True)
    currency = Column(String, nullable=True)
    # RESTRICT
    stage_id = Column(Integer, ForeignKey("stages.id", ondelete="RESTRICT"), nullable=False)

    expected_close_date = Column(Date, nullable=True)
    source = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    account = relationship("Account", lazy="selectin")
    owner   = relationship("User", lazy="selectin")

    business_case = relationship("BusinessCase", uselist=False, back_populates="opportunity", lazy="selectin")


# =========================
# Business Case / Scenario
# =========================
class BusinessCase(Base):
    __tablename__ = "business_cases"
    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)

    opportunity = relationship("Opportunity", back_populates="business_case", lazy="selectin")
    scenarios = relationship("Scenario", back_populates="business_case", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (UniqueConstraint("opportunity_id", name="uix_business_case_opportunity_1to1"),)


class Scenario(Base):
    __tablename__ = "scenarios"
    id = Column(Integer, primary_key=True, index=True)
    business_case_id = Column(Integer, ForeignKey("business_cases.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    months = Column(Integer, nullable=False, default=36)
    start_date = Column(Date, nullable=False)

    is_boq_ready       = Column(Boolean, nullable=False, default=False, server_default="0")
    is_twc_ready       = Column(Boolean, nullable=False, default=False, server_default="0")
    is_capex_ready     = Column(Boolean, nullable=False, default=False, server_default="0")
    is_services_ready  = Column(Boolean, nullable=False, default=False, server_default="0")
    workflow_state     = Column(String,  nullable=False, default="draft", server_default="draft")

    default_price_escalation_policy_id = Column(Integer, ForeignKey("escalation_policies.id", ondelete="SET NULL"), nullable=True)

    # NEW (DB'de mevcut): Capex Reward default %
    default_capex_reward_pct = Column(Numeric(8, 4), nullable=False, default=0)

    business_case = relationship("BusinessCase", back_populates="scenarios", lazy="selectin")
    products   = relationship("ScenarioProduct", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    overheads  = relationship("ScenarioOverhead", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    boq_items  = relationship("ScenarioBOQItem", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    capex_items= relationship("ScenarioCapex", backref="scenario", cascade="all, delete-orphan", lazy="selectin")
    services   = relationship("ScenarioService", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    twc        = relationship("ScenarioTWC", uselist=False, back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    taxes      = relationship("ScenarioTaxRule", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")
    escalation_policies = relationship("ScenarioEscalationPolicy", cascade="all, delete-orphan", lazy="selectin", backref="scenario")

    # NEW: Rebates relationship
    rebates    = relationship("ScenarioRebate", back_populates="scenario", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (Index("ix_scenarios_bc", "business_case_id"),)


# =========================
# Scenario-level: Revenues (Products) & Overheads
# =========================
class ScenarioProduct(Base):
    __tablename__ = "scenario_products"
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    price = Column(Numeric(18, 4), nullable=False, default=0)
    unit_cogs = Column(Numeric(18, 4), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    scenario = relationship("Scenario", back_populates="products", lazy="selectin")
    months = relationship("ScenarioProductMonth", back_populates="product", cascade="all, delete-orphan", lazy="selectin")


class ScenarioProductMonth(Base):
    __tablename__ = "scenario_product_months"
    id = Column(Integer, primary_key=True, index=True)
    scenario_product_id = Column(Integer, ForeignKey("scenario_products.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1..12
    quantity = Column(Numeric(18, 4), nullable=False, default=0)

    product = relationship("ScenarioProduct", back_populates="months", lazy="selectin")


class ScenarioOverhead(Base):
    __tablename__ = "scenario_overheads"
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(20), nullable=False)          # 'fixed' | '%_revenue'
    amount = Column(Numeric(18, 4), nullable=False, default=0)

    scenario = relationship("Scenario", back_populates="overheads", lazy="selectin")


# =========================
# Scenario: CAPEX
# =========================
class ScenarioCapex(Base):
    __tablename__ = "scenario_capex"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False, default=0)
    notes = Column(Text, nullable=True)

    asset_name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    service_start_year = Column(Integer, nullable=True)
    service_start_month = Column(Integer, nullable=True)
    useful_life_months = Column(Integer, nullable=True)
    depr_method = Column(String, nullable=True, default="straight_line")
    salvage_value = Column(Numeric(18, 2), nullable=True, default=0)
    is_active = Column(Boolean, nullable=True, default=True)

    disposal_year = Column(Integer, nullable=True)
    disposal_month = Column(Integer, nullable=True)
    disposal_proceeds = Column(Numeric(18, 2), nullable=True, default=0)
    replace_at_end = Column(Boolean, nullable=True, default=False)
    per_unit_cost = Column(Numeric(18, 2), nullable=True)
    quantity = Column(Integer, nullable=True)
    contingency_pct = Column(Numeric(5, 2), nullable=True, default=0)
    partial_month_policy = Column(String, nullable=True, default="full_month")

    # NEW: Capex Reward sütunları
    reward_enabled = Column(Boolean, nullable=True, default=False)
    reward_pct = Column(Numeric(8, 4), nullable=True)  # yüzde, örn. 50 -> %50
    reward_spread_kind = Column(String, nullable=True, default="even")  # even|follow_boq|custom
    linked_boq_item_id = Column(Integer, nullable=True)  # intentionally no FK (SQLite portability)
    term_months_override = Column(Integer, nullable=True)

    # NEW: direct link to a generated Service row (nullable; no FK for portability)
    linked_service_id = Column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_scenario_capex_linked_service", "linked_service_id"),
    )


# =========================
# Scenario: BOQ
# =========================
class ScenarioBOQItem(Base):
    __tablename__ = "scenario_boq_items"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    section = Column(String(50), nullable=True)
    item_name = Column(String(255), nullable=False)
    unit = Column(String(50), nullable=False)
    quantity = Column(Numeric(18, 4), nullable=False, default=0)
    unit_price = Column(Numeric(18, 4), nullable=False, default=0)
    unit_cogs = Column(Numeric(18, 4), nullable=True)

    # once | monthly | per_shipment | per_tonne
    frequency = Column(String(20), nullable=False, default="once")
    start_year = Column(Integer, nullable=True)
    start_month = Column(Integer, nullable=True)
    months = Column(Integer, nullable=True)

    # NEW: formulation & escalation policy (mevcut)
    formulation_id = Column(Integer, ForeignKey("product_formulations.id", ondelete="SET NULL"), nullable=True)
    price_escalation_policy_id = Column(Integer, ForeignKey("escalation_policies.id", ondelete="SET NULL"), nullable=True)

    # NEW: Product bağlantısı
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product = relationship("Product", lazy="selectin")

    # NEW: Price Term snapshot (UI’nin kaydettiği değer)
    price_term = Column(String, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    notes = Column(Text, nullable=True)

    category = Column(String, nullable=True)

    scenario = relationship("Scenario", back_populates="boq_items", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "category IN ('bulk_with_freight','bulk_ex_freight','freight') OR category IS NULL",
            name="ck_boq_category",
        ),
        CheckConstraint("frequency IN ('once','monthly','per_shipment','per_tonne')", name="ck_boq_frequency"),
        CheckConstraint("(months IS NULL) OR (months >= 1)", name="ck_boq_months"),
        Index("ix_boq_scenario", "scenario_id"),
        Index("ix_boq_product", "product_id"),
    )


# =========================
# Scenario: SERVICES (OPEX)
# =========================
class ScenarioService(Base):
    __tablename__ = "scenario_services"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    service_name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    unit = Column(String, nullable=True)

    quantity = Column(Numeric(18, 4), nullable=False, default=1)
    unit_cost = Column(Numeric(18, 4), nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="TRY")

    start_year = Column(Integer, nullable=False)
    start_month = Column(Integer, nullable=False)
    duration_months = Column(Integer, nullable=True)
    end_year = Column(Integer, nullable=True)
    end_month = Column(Integer, nullable=True)

    payment_term = Column(String, nullable=False, default="monthly")
    cash_out_month_policy = Column(String, nullable=False, default="service_month")

    escalation_pct = Column(Numeric(8, 4), nullable=False, default=0)
    escalation_freq = Column(String, nullable=False, default="none")

    tax_rate = Column(Numeric(8, 4), nullable=False, default=0)
    expense_includes_tax = Column(Boolean, nullable=False, default=False, server_default="0")

    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    formulation_id = Column(Integer, ForeignKey("product_formulations.id", ondelete="SET NULL"), nullable=True)
    price_escalation_policy_id = Column(Integer, ForeignKey("escalation_policies.id", ondelete="SET NULL"), nullable=True)

    scenario = relationship("Scenario", back_populates="services", lazy="selectin")
    months = relationship("ScenarioServiceMonth", back_populates="service", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint("payment_term IN ('monthly','annual_prepaid','one_time')", name="ck_services_payment_term"),
        CheckConstraint("cash_out_month_policy IN ('service_month','start_month','contract_anniversary')", name="ck_services_cash_out_policy"),
        CheckConstraint("escalation_freq IN ('annual','none')", name="ck_services_escalation_freq"),
        Index("ix_services_scenario", "scenario_id"),
        Index("ix_services_active", "is_active"),
    )


class ScenarioServiceMonth(Base):
    __tablename__ = "scenario_service_month"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(Integer, ForeignKey("scenario_services.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    expense_amount = Column(Numeric(18, 2), nullable=False, default=0)
    cash_out = Column(Numeric(18, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(18, 2), nullable=False, default=0)

    service = relationship("ScenarioService", back_populates="months", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("service_id", "year", "month", name="uix_service_month_unique"),
        Index("ix_service_month_sid", "service_id"),
        Index("ix_service_month_ym", "year", "month"),
    )


# =========================
# Scenario FX Rates
# =========================
class ScenarioFXRate(Base):
    __tablename__ = "scenario_fx_rates"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    currency = Column(String(3), nullable=False)
    rate_to_base = Column(Numeric(18, 6), nullable=False, default=1)

    start_year = Column(Integer, nullable=False)
    start_month = Column(Integer, nullable=False)
    end_year = Column(Integer, nullable=True)
    end_month = Column(Integer, nullable=True)

    source = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    scenario = relationship("Scenario", lazy="selectin")

    __table_args__ = (
        CheckConstraint("start_month >= 1 AND start_month <= 12", name="ck_fx_start_month"),
        CheckConstraint("(end_month IS NULL) OR (end_month >= 1 AND end_month <= 12)", name="ck_fx_end_month"),
        UniqueConstraint("scenario_id", "currency", "start_year", "start_month", name="uix_fx_period_unique"),
        Index("ix_fx_scenario", "scenario_id"),
        Index("ix_fx_currency", "currency"),
    )


# =========================
# Scenario Tax Rules
# =========================
class ScenarioTaxRule(Base):
    __tablename__ = "scenario_tax_rules"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(100), nullable=False)
    tax_type = Column(String(20), nullable=False, default="custom")
    applies_to = Column(String(20), nullable=False, default="all")

    rate_pct = Column(Numeric(8, 4), nullable=False, default=0)
    start_year = Column(Integer, nullable=False)
    start_month = Column(Integer, nullable=False)
    end_year = Column(Integer, nullable=True)
    end_month = Column(Integer, nullable=True)

    is_inclusive = Column(Boolean, nullable=False, default=False, server_default="0")
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    scenario = relationship("Scenario", back_populates="taxes", lazy="selectin")

    __table_args__ = (
        CheckConstraint("tax_type IN ('vat','withholding','corp','custom')", name="ck_tax_type"),
        CheckConstraint("applies_to IN ('revenue','services','capex','profit','all')", name="ck_tax_applies_to"),
        CheckConstraint("start_month >= 1 AND start_month <= 12", name="ck_tax_start_month"),
        CheckConstraint("(end_month IS NULL) OR (end_month >= 1 AND end_month <= 12)", name="ck_tax_end_month"),
        Index("ix_tax_scenario", "scenario_id"),
        Index("ix_tax_active", "is_active"),
    )


# =========================
# Scenario Rebates (NEW)
# =========================
class ScenarioRebate(Base):
    __tablename__ = "scenario_rebates"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)

    name = Column(String(255), nullable=False)
    scope = Column(String(20), nullable=False, default="all")          # all|boq|services|product
    kind = Column(String(20), nullable=False, default="percent")       # percent|tier_percent|lump_sum
    basis = Column(String(20), nullable=False, default="revenue")      # revenue|volume

    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)

    valid_from_year  = Column(Integer, nullable=True)
    valid_from_month = Column(Integer, nullable=True)
    valid_to_year    = Column(Integer, nullable=True)
    valid_to_month   = Column(Integer, nullable=True)

    accrual_method = Column(String(20), nullable=False, default="monthly")  # monthly|quarterly|annual|on_invoice
    pay_month_lag  = Column(Integer, nullable=True, default=0)

    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    notes     = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    scenario = relationship("Scenario", back_populates="rebates", lazy="selectin")
    tiers    = relationship("ScenarioRebateTier", back_populates="rebate", cascade="all, delete-orphan", lazy="selectin")
    lumps    = relationship("ScenarioRebateLump", back_populates="rebate", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint("scope IN ('all','boq','services','product')", name="ck_rebate_scope"),
        CheckConstraint("kind IN ('percent','tier_percent','lump_sum')", name="ck_rebate_kind"),
        CheckConstraint("basis IN ('revenue','volume')", name="ck_rebate_basis"),
        CheckConstraint("(valid_from_month IS NULL) OR (valid_from_month BETWEEN 1 AND 12)", name="ck_rebate_from_month"),
        CheckConstraint("(valid_to_month   IS NULL) OR (valid_to_month   BETWEEN 1 AND 12)", name="ck_rebate_to_month"),
        CheckConstraint("accrual_method IN ('monthly','quarterly','annual','on_invoice')", name="ck_rebate_accrual"),
        Index("ix_rebates_scenario", "scenario_id"),
        Index("ix_rebates_active", "is_active"),
    )


class ScenarioRebateTier(Base):
    __tablename__ = "scenario_rebate_tiers"

    id = Column(Integer, primary_key=True, index=True)
    rebate_id = Column(Integer, ForeignKey("scenario_rebates.id", ondelete="CASCADE"), nullable=False)

    min_value = Column(Numeric(18, 6), nullable=False, default=0)
    max_value = Column(Numeric(18, 6), nullable=True)

    percent   = Column(Numeric(9, 4), nullable=True)
    amount    = Column(Numeric(18, 6), nullable=True)

    description = Column(Text, nullable=True)
    sort_order  = Column(Integer, nullable=False, default=0)

    created_at  = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    rebate = relationship("ScenarioRebate", back_populates="tiers", lazy="selectin")

    __table_args__ = (
        CheckConstraint("(percent IS NOT NULL) OR (amount IS NOT NULL)", name="ck_rebate_tier_value"),
        Index("ix_tiers_rebate", "rebate_id", "sort_order"),
        Index("ix_tiers_range", "min_value", "max_value"),
    )


class ScenarioRebateLump(Base):
    __tablename__ = "scenario_rebate_lumps"

    id = Column(Integer, primary_key=True, index=True)
    rebate_id = Column(Integer, ForeignKey("scenario_rebates.id", ondelete="CASCADE"), nullable=False)

    year     = Column(Integer, nullable=False)
    month    = Column(Integer, nullable=False)  # 1..12
    amount   = Column(Numeric(18, 6), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")

    note       = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    rebate = relationship("ScenarioRebate", back_populates="lumps", lazy="selectin")

    __table_args__ = (
        CheckConstraint("month >= 1 AND month <= 12", name="ck_rebate_lump_month"),
        Index("ix_lumps_rebate", "rebate_id"),
        Index("ix_lumps_period", "year", "month"),
    )

# =========================
# Engine (Facts & Runs)
# =========================
class EngineSheet(Base):
    __tablename__ = "engine_sheets"
    code = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    sort_order = Column(Integer, nullable=True, default=0)


class EngineCategory(Base):
    __tablename__ = "engine_categories"
    code = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    sort_order = Column(Integer, nullable=True, default=0)


class EngineRun(Base):
    __tablename__ = "engine_runs"
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, nullable=True)  # intentionally no FK to keep portability
    started_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    options_json = Column(Text, nullable=True)
# Pathway: C:/Dev/AryaIntel_CRM/backend/app/api/__init__.py
"""API package marker (no side-effects). Routers are wired in app/main.py."""
__all__: list[str] = []


class EngineFactMonthly(Base):
    __tablename__ = "engine_facts_monthly"
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, nullable=True)  # intentionally no FK for portability
    scenario_id = Column(Integer, nullable=True)

    sheet_code = Column(String, ForeignKey("engine_sheets.code", ondelete="RESTRICT"), nullable=False)
    category_code = Column(String, ForeignKey("engine_categories.code", ondelete="RESTRICT"), nullable=False)

    yyyymm = Column(Integer, nullable=False)  # YYYYMM
    value = Column(Numeric(18, 6), nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "sheet_code", "category_code", "yyyymm", name="ux_engine_facts"),
        Index("ix_engine_facts_scenario", "scenario_id", "yyyymm"),
    )
