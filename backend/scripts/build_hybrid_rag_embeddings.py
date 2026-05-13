import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.hybrid_store import HybridRagStore  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Construye embeddings para RAG híbrido sobre rag_child_chunks.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = await HybridRagStore().build(limit=args.limit, force=args.force, batch_size=args.batch_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
