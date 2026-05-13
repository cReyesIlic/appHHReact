"""CLI para sincronizar SharePoint → Master/RAG/Wiki.

Subcomandos:
  status                         Cobertura actual.
  discover-new [--limit 200]     Lista códigos nuevos en SP sin RAG.
  sync-new [--limit 20]          Descarga + indexa + wiki para los nuevos.
  sync-code O-XXXX               Sincroniza un código específico.
  backfill-wiki [--limit N]      Compila páginas Wiki para los que tienen RAG sin página.
  backfill-wiki --dry-run        Muestra cuántos faltan sin gastar tokens.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.proposal_sync_service import ProposalSyncService  # noqa: E402


async def cmd_status() -> None:
    svc = ProposalSyncService()
    gap = svc.discover_wiki_gaps()
    print(json.dumps(gap | {"missing_codes": gap["missing_codes"][:15]}, ensure_ascii=False, indent=2))


async def cmd_discover_new(limit: int) -> None:
    svc = ProposalSyncService()
    result = await svc.discover_new(limit=limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def cmd_sync_new(limit: int, force_wiki: bool) -> None:
    svc = ProposalSyncService()
    result = await svc.sync_new(limit=limit, force_wiki=force_wiki)
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, ensure_ascii=False, indent=2))
    print(f"\n({len(result.get('details', []))} detalles guardados en storage/sync_manifest.csv)")


async def cmd_sync_code(codigo: str, force_wiki: bool) -> None:
    svc = ProposalSyncService()
    result = await svc.sync_code(codigo, force_wiki=force_wiki)
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def cmd_backfill_wiki(limit: int | None, force: bool, dry_run: bool, concurrency: int) -> None:
    svc = ProposalSyncService()
    if dry_run:
        gap = svc.discover_wiki_gaps()
        total = gap["missing_wiki"]
        target = min(limit or total, total)
        # estimación rápida: ~3500 tokens input + ~1200 output por entrada con gpt-4o-mini
        est_input = target * 3500
        est_output = target * 1200
        # pricing aproximado gpt-4o-mini: $0.15 / 1M input, $0.60 / 1M output
        est_cost = (est_input * 0.15 + est_output * 0.60) / 1_000_000
        # tiempo paralelo: ~25s por entrada / concurrency
        seq_min = int(target * 25 / 60)
        par_min = int(target * 25 / 60 / max(1, concurrency))
        print(f"Pendientes (con RAG, sin wiki): {total}")
        print(f"Objetivo de esta corrida:        {target}")
        print(f"Concurrencia:                    {concurrency}")
        print(f"Tokens estimados:                ~{est_input:,} input + ~{est_output:,} output")
        print(f"Costo estimado (gpt-4o-mini):    ~${est_cost:.2f} USD")
        print(f"Tiempo estimado secuencial:      ~{seq_min} min")
        print(f"Tiempo estimado paralelo x{concurrency}:    ~{par_min} min")
        return
    t0 = time.time()
    result = await svc.backfill_wiki(force=force, limit=limit, concurrency=concurrency)
    elapsed = int(time.time() - t0)
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, ensure_ascii=False, indent=2))
    print(f"\nTiempo: {elapsed}s | Detalles en storage/sync_manifest.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronización SharePoint → RAG → Wiki.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    p_discover = sub.add_parser("discover-new")
    p_discover.add_argument("--limit", type=int, default=200)

    p_sync_new = sub.add_parser("sync-new")
    p_sync_new.add_argument("--limit", type=int, default=20)
    p_sync_new.add_argument("--force-wiki", action="store_true")

    p_sync_code = sub.add_parser("sync-code")
    p_sync_code.add_argument("codigo")
    p_sync_code.add_argument("--force-wiki", action="store_true")

    p_backfill = sub.add_parser("backfill-wiki")
    p_backfill.add_argument("--limit", type=int, default=None)
    p_backfill.add_argument("--force", action="store_true")
    p_backfill.add_argument("--dry-run", action="store_true")
    p_backfill.add_argument("--concurrency", type=int, default=8)

    args = parser.parse_args()

    if args.cmd == "status":
        asyncio.run(cmd_status())
    elif args.cmd == "discover-new":
        asyncio.run(cmd_discover_new(args.limit))
    elif args.cmd == "sync-new":
        asyncio.run(cmd_sync_new(args.limit, args.force_wiki))
    elif args.cmd == "sync-code":
        asyncio.run(cmd_sync_code(args.codigo, args.force_wiki))
    elif args.cmd == "backfill-wiki":
        asyncio.run(cmd_backfill_wiki(args.limit, args.force, args.dry_run, args.concurrency))


if __name__ == "__main__":
    main()
