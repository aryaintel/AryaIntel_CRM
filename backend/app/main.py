# Pathway: C:/Dev/AryaIntel_CRM/backend/app/main.py
from fastapi import FastAPI, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .api.deps import get_current_user, CurrentUser

# ---- Routers ----
# Pricing & formulation
from .api import service_pricing, boq_pricing, formulations_api, formulation_links_api
from .api.escalation import router as escalation_router  # FIX: was escalation_routera
from .api.rise_fall_api import router as rise_fall_router
from .api.rebates_runtime import router as rebates_runtime_router
from .api.scenario_summary import router as scenario_summary_router
from .api.price_terms import router as price_terms_router
from .api import cost_books_api
from .api.services_catalog_api import router as services_catalog_router

# Run Engine APIs
from .api.run_engine_api import router as run_engine_router
from .api.engine_facts_api import router as engine_facts_router     # FIX: use engine_facts_api
from .api.boq_diagnostics_api import router as boq_diag_router      # NEW: BOQ diagnostics

# Core modules
from .api import (
    auth,
    accounts,
    contacts,
    deals,
    users,
    roles,
    secure,
    leads,
    business_cases,
    stages,
    scenario_boq as boq,
    twc,
    scenario_capex,
    scenario_services,
    scenario_overheads,
    scenario_fx,
    scenario_tax,
    workflow,
    index_series_api,
    escalations_api,
)

from .api.products_api import router as products_router
from .api.cost_books_api import router as cost_books_router
from .api.rebates_api import router as rebates_router
from .api.db_schema import router as db_schema_router
from .api.opex_api import router as opex_router

app = FastAPI(
    title="Arya CRM API",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost",
    "http://127.0.0.1",
]

def _resolve_allowed_origins() -> list[str]:
    raw = getattr(settings, "CORS_ALLOW_ORIGINS", None)
    if not raw:
        return DEFAULT_CORS_ORIGINS
    if isinstance(raw, (list, tuple)):
        vals = [str(x).strip().rstrip("/") for x in raw if str(x).strip()]
    else:
        vals = [s.strip().rstrip("/") for s in str(raw).split(",") if s.strip()]
    if len(vals) == 1 and vals[0] == "*":
        return DEFAULT_CORS_ORIGINS
    return vals or DEFAULT_CORS_ORIGINS

ALLOW_ORIGINS = _resolve_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and (origin in ALLOW_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        prev_vary = response.headers.get("Vary")
        response.headers["Vary"] = "Origin" if not prev_vary else (
            prev_vary if "Origin" in (prev_vary or "").split(",") else f"{prev_vary}, Origin"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# ---------------------------
# Health & Current User
# ---------------------------
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}

@app.get("/me", tags=["auth"])
def me(current: CurrentUser = Depends(get_current_user)):
    return {
        "id": current.id,
        "email": current.email,
        "tenant_id": current.tenant_id,
        "role": current.role_name,
    }

@app.get("/auth/me", tags=["auth"], status_code=status.HTTP_200_OK)
def me_alias(current: CurrentUser = Depends(get_current_user)):
    return {
        "id": current.id,
        "email": current.email,
        "tenant_id": current.tenant_id,
        "role": current.role_name,
    }

# ---------------------------
# Routers
# ---------------------------
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(contacts.router)
app.include_router(deals.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(secure.router)
app.include_router(leads.router)
app.include_router(stages.router)

app.include_router(business_cases.router)
app.include_router(boq.router)
app.include_router(twc.router)
app.include_router(scenario_capex.router)
app.include_router(scenario_services.router)
app.include_router(scenario_overheads.router)
app.include_router(scenario_fx.router)
app.include_router(scenario_tax.router)
app.include_router(rebates_router)
app.include_router(scenario_summary_router)

# Mount workflow under /api to match FE paths
app.include_router(workflow.router, prefix="/api")

app.include_router(service_pricing.router)
app.include_router(boq_pricing.router)
app.include_router(formulations_api.router)
app.include_router(formulation_links_api.router)

app.include_router(index_series_api.router)
app.include_router(escalations_api.router)
app.include_router(escalation_router)
app.include_router(rise_fall_router)

app.include_router(products_router)
app.include_router(cost_books_router)
app.include_router(cost_books_api.router_products)

app.include_router(rebates_runtime_router)

app.include_router(db_schema_router)
app.include_router(price_terms_router)

# Engine & diagnostics
app.include_router(run_engine_router)
app.include_router(engine_facts_router)
app.include_router(boq_diag_router)

# Other domain APIsd
app.include_router(opex_router)
app.include_router(services_catalog_router)
