"""Backfill: corre la Azure Function `budget-extractor` para todas las propuestas PG
con Excel local pendiente, y persiste resultados en SQLite.

Uso:
    python -m scripts.backfill_budget_extractor              # todas
    python -m scripts.backfill_budget_extractor --limit 10   # solo 10
    python -m scripts.backfill_budget_extractor --estado PG  # filtrar estado

Requiere BUDGET_EXTRACTOR_URL y BUDGET_EXTRACTOR_API_KEY en env.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sqlite3
import sys
import time
from pathlib import Path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--estado", default="PG")
    parser.add_argument("--skip-empty", action="store_true", default=True)
    parser.add_argument("--retry", action="store_true", help="Reintenta códigos que ya tienen extracción")
    args = parser.parse_args()

    from app.services.budget_extractor_client import BudgetExtractorClient
    from app.core.config import settings

    client = BudgetExtractorClient()
    if not client.available:
        print("ERROR: BUDGET_EXTRACTOR_URL no configurada", file=sys.stderr)
        return 1

    conn = sqlite3.connect(settings.sqlite_path)
    estado = args.estado
    pg_codes = {r[0].upper() for r in conn.execute(f"select codigo from oferta where estado=?", (estado,)).fetchall() if r[0]}
    already = set() if args.retry else {r[0].upper() for r in conn.execute("select distinct codigo from proyectos_extracted").fetchall() if r[0]}
    conn.close()

    base = settings.resolve_path("storage/emitted_offer_assets/excel")
    candidates: list[tuple[str, str]] = []
    for code in sorted(pg_codes - already):
        folder = base / code
        if not folder.is_dir():
            continue
        excels = sorted(list(folder.glob("*.xlsx")) + list(folder.glob("*.xlsm")))
        if not excels:
            continue
        hh = [e for e in excels if e.name.upper().startswith("HH")]
        candidates.append((code, str(hh[0] if hh else excels[0])))

    if args.limit > 0:
        candidates = candidates[: args.limit]

    print(f"Backfill: {len(candidates)} propuestas a procesar")
    print(f"  Storage: {settings.sqlite_path}")
    print()

    ok = empty = errors = 0
    start = time.time()
    for i, (code, path) in enumerate(candidates, 1):
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            extracted = await client.extract_normalized(code, content, os.path.basename(path))
            if extracted.get("error"):
                errors += 1
                print(f"[{i}/{len(candidates)}] {code} ERROR: {extracted['error'][:100]}")
                continue
            totals = extracted.get("totals") or {}
            n_proyecto = int(totals.get("proyecto_filas") or 0)
            n_tarifas = int(totals.get("tarifas_filas") or 0)
            n_gastos = int(totals.get("gastos_filas") or 0)
            if args.skip_empty and (n_proyecto + n_tarifas + n_gastos) == 0:
                empty += 1
                print(f"[{i}/{len(candidates)}] {code} skip (sin filas) | {os.path.basename(path)}")
                continue
            persisted = client.persist(code, os.path.basename(path), extracted)
            ok += 1
            print(f"[{i}/{len(candidates)}] {code} OK filas={persisted['proyecto_filas']} tarifas={persisted['tarifas_filas']} gastos={persisted['gastos_filas']}")
        except Exception as exc:
            errors += 1
            print(f"[{i}/{len(candidates)}] {code} EXC: {type(exc).__name__}: {exc}")

    elapsed = time.time() - start
    print()
    print(f"=== RESUMEN ===")
    print(f"  Procesadas: {len(candidates)}")
    print(f"  OK: {ok}")
    print(f"  Sin datos (skip): {empty}")
    print(f"  Errores: {errors}")
    print(f"  Tiempo: {elapsed:.1f}s ({elapsed / max(1, len(candidates)):.1f}s/excel)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
