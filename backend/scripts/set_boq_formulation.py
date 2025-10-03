# backend/scripts/set_boq_formulation.py
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = (Path(__file__).resolve().parents[1] / "app.db").as_posix()


def _db() -> sqlite3.Connection:
    cx = sqlite3.connect(DB_PATH)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON;")
    return cx


def _get_formulation_by_code(cx: sqlite3.Connection, code: str, product_id: Optional[int]) -> Optional[sqlite3.Row]:
    if product_id is not None:
        return cx.execute(
            "SELECT id, code FROM product_formulations WHERE code=? AND product_id=?",
            (code, product_id),
        ).fetchone()
    return cx.execute(
        "SELECT id, code FROM product_formulations WHERE code=? ORDER BY id DESC LIMIT 1",
        (code,),
    ).fetchone()


def _get_latest_formulation(cx: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return cx.execute("SELECT id, code FROM product_formulations ORDER BY id DESC LIMIT 1").fetchone()


def main():
    p = argparse.ArgumentParser(
        description="Link a formulation to a BOQ line (scenario_boq_items).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--boq-id", type=int, required=True, help="scenario_boq_items.id")
    grp = p.add_mutually_exclusive_group(required=False)
    grp.add_argument("--formulation-id", type=int, help="product_formulations.id to assign")
    grp.add_argument("--formulation-code", type=str, help="product_formulations.code to search")
    p.add_argument("--product-id", type=int, help="(optional) filter when searching by code")
    p.add_argument("--use-latest", action="store_true", help="if no formulation provided, use latest formulation")
    args = p.parse_args()

    with _db() as cx:
        # Check BOQ row
        boq = cx.execute(
            "SELECT id, item_name, formulation_id FROM scenario_boq_items WHERE id=?",
            (args.boq_id,),
        ).fetchone()
        if not boq:
            raise SystemExit(f"[x] BOQ line id={args.boq_id} not found")

        # Resolve formulation
        target = None
        if args.formulation_id:
            target = cx.execute(
                "SELECT id, code FROM product_formulations WHERE id=?",
                (args.formulation_id,),
            ).fetchone()
            if not target:
                raise SystemExit(f"[x] formulation_id={args.formulation_id} not found")
        elif args.formulation_code:
            target = _get_formulation_by_code(cx, args.formulation_code, args.product_id)
            if not target:
                hint = f" (product_id={args.product_id})" if args.product_id else ""
                raise SystemExit(f"[x] formulation with code='{args.formulation_code}'{hint} not found")
        elif args.use_latest:
            target = _get_latest_formulation(cx)
            if not target:
                raise SystemExit("[x] no formulations in database to pick as latest")
        else:
            # Nothing specified → friendly message
            raise SystemExit(
                "[x] Provide one of --formulation-id / --formulation-code [/ --product-id] or --use-latest"
            )

        # Do update
        cx.execute(
            "UPDATE scenario_boq_items SET formulation_id=? WHERE id=?",
            (int(target["id"]), int(boq["id"])),
        )

        # Verify
        new_row = cx.execute(
            "SELECT id, item_name, formulation_id FROM scenario_boq_items WHERE id=?",
            (args.boq_id,),
        ).fetchone()

        print(
            f"[✓] Bağlandı: boq_id={new_row['id']} '{boq['item_name']}' "
            f"-> formulation_id={new_row['formulation_id']} (code={target['code']})"
        )


if __name__ == "__main__":
    main()
