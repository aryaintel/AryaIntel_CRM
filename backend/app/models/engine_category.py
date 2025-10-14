# Pathway: C:/Dev/AryaIntel_CRM/backend/app/models/engine_category.py
from typing import Optional
from sqlalchemy import text
from sqlalchemy.engine import Connection

# Valid engine category codes
CODES = ("AN", "EM", "IE", "Services")

def product_category(conn: Connection, product_id: int) -> Optional[str]:
    """
    Resolve engine category for a product:
      1) engine_category_map scope='product' override
      2) engine_category_map scope='product_family' by product.family_id
      3) None if not found
    """
    # 1) product override
    row = conn.execute(text("""
        SELECT category_code FROM engine_category_map
        WHERE scope='product' AND ref_id=:pid AND is_active=1
        LIMIT 1
    """), {"pid": product_id}).fetchone()
    if row and row[0] in CODES:
        return row[0]

    # 2) family mapping
    fam = conn.execute(text("SELECT family_id FROM products WHERE id=:pid"), {"pid": product_id}).fetchone()
    if fam and fam[0] is not None:
        row = conn.execute(text("""
            SELECT category_code FROM engine_category_map
            WHERE scope='product_family' AND ref_id=:fid AND is_active=1
            LIMIT 1
        """), {"fid": int(fam[0])}).fetchone()
        if row and row[0] in CODES:
            return row[0]
    return None
