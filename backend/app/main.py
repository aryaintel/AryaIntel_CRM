# backend/app/main.py
from fastapi import FastAPI, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .api.deps import get_current_user, CurrentUser

# ---- Routers ----
# Pricing & formulation
from .api import service_pricing, boq_pricing, formulations_api, formulation_links_api
from .api.escalation import router as escalation_router
from app.api.rise_fall_api import router as rise_fall_router  # keep absolute to match pkg layout
from app.api.rebates_runtime import router as rebates_runtime_router
from app.api.scenario_summary import router as scenario_summary_router  # unified Summary API
from app.api.price_terms import router as price_terms_router

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
    workflow,                 # mounted under /api below
    index_series_api,         # has its own "/api/index-series" prefix
    escalations_api,          # check below for mount (already API-prefixed in router)
)

# Products & Price Books
from .api.products_api import router as products_router

# Rebates (Scenario-level CRUD)
from .api.rebates_api import router as rebates_router
from .api.db_schema import router as db_schema_router


app = FastAPI(title="Arya CRM API")

# ---------------------------
# CORS (frontend dev servers)
# ---------------------------
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

# 1) CORSMiddleware — must be added BEFORE routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2) Safety net: enforce proper CORS headers on all responses
@app.middleware("http")
async def ensure_cors_headers(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and (origin in ALLOW_ORIGINS):
        response.headers["Access-Control-Allow-Origin"] = origin
        prev_vary = response.headers.get("Vary")
        response.headers["Vary"] = "Origin" if not prev_vary else (
            prev_vary if "Origin" in prev_vary.split(",") else prev_vary + ", Origin"
        )
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.middleware("http")
async def _debug_auth(request: Request, call_next):
    if request.url.path.startswith("/api/scenarios/") and ("/rebates" in request.url.path):
        print(
            ">>> DEBUG REBATES CALL",
            "Path=", request.url.path,
            "Origin=", request.headers.get("origin"),
            "Cookie=", bool(request.headers.get("cookie")),
        )
    return await call_next(request)


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


# Legacy alias for older frontends
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

# Auth & basic CRM
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(contacts.router)
app.include_router(deals.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(secure.router)
app.include_router(leads.router)
app.include_router(stages.router)

# Business cases & scenarios
app.include_router(business_cases.router)
app.include_router(boq.router)                   # BOQ
app.include_router(twc.router)                   # TWC
app.include_router(scenario_capex.router)        # CAPEX
app.include_router(scenario_services.router)     # SERVICES (OPEX)
app.include_router(scenario_overheads.router)    # Overheads
app.include_router(scenario_fx.router)           # FX
app.include_router(scenario_tax.router)          # TAX
app.include_router(rebates_router)               # REBATES (CRUD)
app.include_router(scenario_summary_router)      # SUMMARY (BOQ + rebates overlay)

# Workflow & pricing/escalation
# IMPORTANT: Standardize workflow under /api to match FE (`/api/scenarios/...`)
app.include_router(workflow.router, prefix="/api")

app.include_router(service_pricing.router)       # PRICE PREVIEW (service)
app.include_router(boq_pricing.router)           # PRICE PREVIEW (boq)
app.include_router(formulations_api.router)      # FORMULATIONS CRUD
app.include_router(formulation_links_api.router)

# These routers ALREADY declare API prefixes; do NOT add another prefix here.
app.include_router(index_series_api.router)      # exposes /api/index-series/...
app.include_router(escalations_api.router)       # exposes /api/escalations/... (as defined in module)

app.include_router(escalation_router)
app.include_router(rise_fall_router)

# Products & Price Books
app.include_router(products_router)

# Rebates runtimfe (preview endpoint used by Summary & others)
app.include_router(rebates_runtime_router)

# Debug & tooling
app.include_router(db_schema_router)
app.include_router(price_terms_router)                    # <- add