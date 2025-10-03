from sqlalchemy import create_engine, text
import os, re, sqlite3

# 1) Aynı DB'yi kullanalım: önce settings, sonra env, sonra fallback
db_url = None
try:
    from core.config import settings  # projendeki config ise
    db_url = getattr(settings, "DATABASE_URL", None) or getattr(settings, "SQLALCHEMY_DATABASE_URI", None)
except Exception:
    pass
db_url = db_url or os.getenv("DATABASE_URL") or "sqlite:///./app.db"

print(f"[info] Using DB URL: {db_url}")

# 2) SQLAlchemy ile dene
engine = create_engine(db_url)

def list_sqlite_tables_from_path(db_path: str):
    p = os.path.abspath(db_path)
    print(f"[debug] Inspecting sqlite file: {p}")
    con = sqlite3.connect(p)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print("[debug] tables:", tables)
    return tables

def sqlite_path_from_url(url: str) -> str | None:
    if not url.startswith("sqlite"):
        return None
    # sqlite:///C:/path/file.db  or sqlite:///./app.db
    m = re.match(r"^sqlite:/*(.*)$", url)
    if not m: 
        return None
    path = m.group(1)
    # strip leading slashes used by URL form
    while path.startswith("/"):
        path = path[1:]
    # Windows drive fix: if it contains : keep as-is
    return path

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, date_month, year, month, year_month, quarter, month_name
            FROM calendar_months
            ORDER BY date_month
            LIMIT 10
        """))
        rows = result.fetchall()
        if rows:
            print("[ok] sample rows:")
            for r in rows:
                print(r)
        else:
            print("[warn] No rows in calendar_months.")
except Exception as e:
    print(f"[error] Query failed: {e}")
    # Eğer sqlite ise, dosyadaki tablo listesini göster
    p = sqlite_path_from_url(db_url)
    if p:
        list_sqlite_tables_from_path(p)
    print("[hint] Eğer 'calendar_months' listede yoksa, doğru DB'ye 'alembic upgrade head' uygulayın.")

