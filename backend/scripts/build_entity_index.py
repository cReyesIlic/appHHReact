import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.entity_index import EntityIndex  # noqa: E402


def main() -> None:
    index = EntityIndex()
    result = index.rebuild_from_rag()
    result["status"] = index.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
