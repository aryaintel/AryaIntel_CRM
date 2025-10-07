# backend/scripts/ensure_price_term_on_price_book_entries.py
"""
price_book_entries tablosuna price_term kolonu ve doğrulama trigger'larını (yoksa) EKLER.
SQLite app.db için tasarlandı.

Çalıştırma:
    cd backend
    python scripts/ensure_price_term_on_price_book_entries.py
"""
import sqlite3
from pathlib import Path
from typing import Optional, Sequence, Tuple, Any

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"

ALLOWED_TERMS = ("bulk_with_freight", "bulk_ex_freight", "freight")

DDL_ADD_COLUMN = """
ALTER TABLE price_book_entries
ADD COLUMN price_term TEXT NULL;
"""

# SQLite'ta mevcut tabloya sonradan CHECK constraint ekleyemediğimiz için,
# INSERT/UPDATE öncesi doğrulayan tetikleyiciler kullanıyoruz.
DDL_TRIGGERS = f"""
CREATE TRIGGER IF NOT EXISTS trg_pbe_price_term_chk_insert
BEFORE INSERT ON price_book_entries
FOR EACH ROW
WHEN NEW.price_term IS NOT NULL
 AND NEW.price_term NOT IN {ALLOWED_TERMS}
BEGIN
    SELECT RAISE(ABORT, 'invalid price_term');
END;

CREATE TRIGGER IF NOT EXISTS trg_pbe_price_term_chk_update
BEFORE UPDATE OF price_term ON price_book_entries
FOR EACH ROW
WHEN NEW.price_term IS NOT NULL
 AND NEW.price_term NOT IN {ALLOWED_TERMS}
BEGIN
    SELECT RAISE(ABORT, 'invalid price_term');
END;
"""

def table_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (name,)
    )
    return cur.fetchone() is not None

def column_exists(cx: sqlite3.Connection, table: str, column: str) -> bool:
    cur = cx.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cur.fetchall()]  # row[1] = column name
    return column in cols

def trigger_exists(cx: sqlite3.Connection, name: str) -> bool:
    cur = cx.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?;", (name,)
    )
    return cur.fetchone() is not None

def safe_executescript(cx: sqlite3.Connection, sql: str) -> None:
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        try:
            cx.execute(stmt + ";")
        except sqlite3.Error as e:
            print(f"[!] Skip DDL (possibly exists): {stmt[:60]}... :: {e}")

def get_rowcount(
    cx: sqlite3.Connection,
    where: Optional[str] = None,
    params: Sequence[Any] | Tuple[Any, ...] = (),
) -> int:
    sql = "SELECT COUNT(*) FROM price_book_entries"
    if where:
        sql += f" WHERE {where}"
    return cx.execute(sql, tuple(params)).fetchone()[0]

def main():
    print(f"[i] DB: {DB_PATH}")
    cx = sqlite3.connect(str(DB_PATH))
    cx.execute("PRAGMA foreign_keys = ON;")

    if not table_exists(cx, "price_book_entries"):
        print("[x] Tablo bulunamadı: price_book_entries — önce tabloyu oluşturmalısınız.")
        return

    # 1) price_term kolonu yoksa ekle
    if not column_exists(cx, "price_book_entries", "price_term"):
        print("[+] price_term kolonu ekleniyor ...")
        cx.executescript(DDL_ADD_COLUMN)
    else:
        print("[=] price_term kolonu zaten var.")

    # 2) Doğrulama trigger'ları
    if not (trigger_exists(cx, "trg_pbe_price_term_chk_insert")
            and trigger_exists(cx, "trg_pbe_price_term_chk_update")):
        print("[+] price_term doğrulama trigger'ları oluşturuluyor ...")
        safe_executescript(cx, DDL_TRIGGERS)
    else:
        print("[=] price_term doğrulama trigger'ları zaten var.")

    # 3) (Opsiyonel) Geçersiz değerleri NULL yap
    invalid_count = get_rowcount(
        cx,
        f"price_term IS NOT NULL AND price_term NOT IN {ALLOWED_TERMS}",
    )
    if invalid_count > 0:
        print(f"[!] {invalid_count} satırda geçersiz price_term bulundu. NULL'a çekiliyor ...")
        cx.execute(
            f"UPDATE price_book_entries "
            f"SET price_term = NULL "
            f"WHERE price_term IS NOT NULL AND price_term NOT IN {ALLOWED_TERMS};"
        )

    cx.commit()  # DDL + temizlik

    # 4) Kısa özet
    total = get_rowcount(cx)
    nulls = get_rowcount(cx, "price_term IS NULL")
    term_counts = {
        term: get_rowcount(cx, "price_term = ?", (term,))
        for term in ALLOWED_TERMS
    }

    print(f"[✓] price_book_entries hazır. Toplam: {total}, NULL: {nulls}, dağılım: {term_counts}")
    cx.close()

if __name__ == "__main__":
    main()
