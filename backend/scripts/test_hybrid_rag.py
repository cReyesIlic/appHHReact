import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.hybrid_store import HybridRagStore  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba busqueda híbrida.")
    parser.add_argument("query")
    parser.add_argument("--codes", default="")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    codes = [code.strip().upper() for code in args.codes.split(",") if code.strip()] or None
    hits = await HybridRagStore().search(args.query, codes=codes, limit=args.limit)
    print(json.dumps({"hits": hits}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
