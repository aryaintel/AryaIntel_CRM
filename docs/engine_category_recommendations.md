# Engine Category Code Integration Plan

This document outlines the backend and frontend work required to capture the
engine category code (`AN`, `EM`, `IE`, or `Services`) whenever a product family
or individual product is created or edited. The goal is to surface the category
selection in the UI and persist it through the API without altering existing
runtime behaviour that depends on `engine_category_map`.

## Backend

### 1. Persist category assignments alongside create/update flows

- **File:** `backend/app/api/products_api.py`
  - Ensure `_ensure_schema` also provisions the `engine_category_map` table by
    importing and reusing the logic from
    `backend/scripts/20251015_add_engine_category_map.py` (or inlining a minimal
    `CREATE TABLE IF NOT EXISTS` + unique index statement).
  - Extend `create_product_family` and `update_product_family` so they accept an
    optional `category_code` field. After the existing insert/update, perform an
    upsert into `engine_category_map` with `scope='product_family'`. Delete or
    deactivate any prior row when the field is omitted.
  - Extend `create_product` and `update_product` to accept the same
    `category_code` payload key (validated against the tuple declared in
    `backend/app/models/engine_category.py`). Use an upsert into
    `engine_category_map` with `scope='product'` so overrides are saved per
    product. This preserves the existing fallback behaviour (product override
    beats family mapping) implemented by `product_category`.
  - When returning rows from `list_product_families`, `get_product`, and
    `list_products`, join against `engine_category_map` (respecting `scope` and
    `is_active=1`) so the resolved `category_code` is surfaced in the API
    response (`family_category_code` for families, `category_code` for products).
  - Introduce a small helper inside this module to handle the "upsert or delete"
    logic for the mapping table to keep the CRUD handlers concise.

### 2. Validation + typing helpers

- **File:** `backend/app/models/engine_category.py`
  - Export the `CODES` tuple (already present) as the single source of truth for
    valid codes and add a convenience `is_valid_code(value: str) -> bool` helper.
  - Import this helper in the API layer to validate incoming payloads with a
    clean 422 error message when an invalid code is posted.

### 3. Database migrations / scripts

- **File:** `backend/scripts/20251015_add_engine_category_map.py`
  - Update the script to include a reusable `ensure_schema(engine)` function so
    it can be imported by the API module to provision the table during
    application startup.
  - (Optional) Add a companion script to backfill existing products/families by
    prompting for manual categorisation or applying heuristics similar to the
    current seeding logic.

## Frontend

### 1. Surface category selection in CRUD forms

- **File:** `frontend/src/pages/ProductsPage.tsx`
  - Extend the product edit/create drawer state with a `category_code` field.
  - Render a `<select>` element listing the four codes. Persist the chosen value
    when saving by including it in the POST/PUT payloads sent via `apiPost` and
    `apiPatch` wrappers.
  - Display the resolved category in the product detail panel and in the list
    (e.g., `Family: Bulk Emulsion • Category: EM`) so users can confirm the
    assignment.

- **File:** `frontend/src/pages/products/ProductFamiliesPage.tsx`
  - Add a similar dropdown for family creation/editing. Because families define
    the default category for their products, label the field accordingly (e.g.,
    "Engine Category Code"). Ensure updates call the amended backend endpoint.
  - When showing a selected family, include the active category code in the
    summary card.

### 2. Share the allowed code list in one place

- **File:** `frontend/src/lib/apiProducts.ts`
  - Update the TypeScript types for `Product` and `ProductFamily` to include an
    optional `category_code` (for products) and `family_category_code` (for
    families). Export a constant array `ENGINE_CATEGORY_CODES = ["AN", "EM",
    "IE", "Services"]` so UI components can import it rather than retyping the
    options.

- **File:** `frontend/src/components/ProductPicker.tsx` and any other pickers
  that fetch product lists should adjust their typings/rendering to handle the
  additional field so category information is preserved when products are
  selected elsewhere in the app.

### 3. Visual validation / UX polish

- Provide helper text that explains the meaning of each code (tooltip or inline
  hint) to reduce user confusion.
- Optionally default the dropdown to the family-level category when creating a
  new product to reinforce the override hierarchy (product-specific selection is
  optional).

## QA considerations

- Verify that historical products/families without a category continue to work;
  the API should return `null` for the new fields until the user assigns a code.
- Ensure the BOQ, Pricing, and Scenario flows that call `product_category`
  continue to receive the same results thanks to the shared mapping table.
- Add API tests (FastAPI `TestClient`) covering create/update payloads with
  valid/invalid codes and the family-to-product inheritance logic.

## Deployment notes

- The schema change is additive and idempotent when using the helper to create
  `engine_category_map`. Run the updated migration script once in each
  environment before deploying the API so legacy rows exist.
- Coordinate release so the backend is deployed before the frontend to avoid
  frontend requests sending `category_code` to an endpoint that does not yet
  accept it.
