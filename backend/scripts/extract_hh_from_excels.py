import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.hh_excel_extractor import HHExcelExtractor  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrae entregables, actividades, HH y tarifas desde Excel emitidos.")
    parser.add_argument("--manifest", default="storage/emitted_offer_assets/manifest.csv")
    parser.add_argument("--state", default="storage/hh_excel_ingestion_manifest.csv")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest_path = settings.resolve_path(args.manifest)
    state_path = settings.resolve_path(args.state)
    state = {row["key"]: row for row in read_csv(state_path)}
    files = expand_excel_rows(read_csv(manifest_path))
    extractor = HHExcelExtractor()
    processed = []

    for item in files:
        if args.limit and len(processed) >= args.limit:
            break
        key = item["key"]
        if not args.force and state.get(key, {}).get("status") == "ok":
            continue
        result = extractor.extract_file(item["codigo"], item["local_path"])
        processed.append(status_row(item, result))
        save_csv(state_path, merge(state, processed))

    save_csv(state_path, merge(state, processed))
    print(json.dumps({"processed": len(processed), "state": str(state_path), "summary": extractor.summary()}, ensure_ascii=False, indent=2))


def expand_excel_rows(rows: list[dict]) -> list[dict]:
    expanded = []
    for row in rows:
        if row.get("status") != "ok":
            continue
        codigo = str(row.get("codigo", "")).strip().upper()
        names = split_multi(row.get("selected_excel"))
        paths = split_multi(row.get("selected_excel_local"))
        for index, path in enumerate(paths):
            add_excel(expanded, codigo, path, names[index] if index < len(names) else Path(path).name, "selected_excel")
        for asset in parse_zip_assets(row.get("zip_assets")):
            add_excel(expanded, codigo, asset["local_path"], asset["excel_name"], "zip_extracted")
    return expanded


def add_excel(rows: list[dict], codigo: str, path: str, name: str, source: str) -> None:
    suffix = Path(path).suffix.lower()
    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        return
    if not Path(path).exists():
        return
    rows.append(
        {
            "key": f"{codigo}:{Path(path).resolve()}",
            "codigo": codigo,
            "excel_name": name,
            "local_path": path,
            "source": source,
        }
    )


def split_multi(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split("||") if part.strip()]


def parse_zip_assets(value: str | None) -> list[dict]:
    try:
        assets = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    rows = []
    for asset in assets if isinstance(assets, list) else []:
        for extracted in asset.get("extracted", []) if isinstance(asset, dict) else []:
            local = extracted.get("local", "")
            source = extracted.get("source", "")
            if Path(local).suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
                rows.append({"local_path": local, "excel_name": source or Path(local).name})
    return rows


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def save_csv(path: Path, rows_by_key: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["key", "codigo", "status", "excel_name", "local_path", "rows", "error", "updated_at"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows_by_key.values(), key=lambda item: item["key"]):
            writer.writerow({field: row.get(field, "") for field in fields})


def merge(existing: dict[str, dict], rows: list[dict]) -> dict[str, dict]:
    merged = dict(existing)
    for row in rows:
        merged[row["key"]] = row
    return merged


def status_row(item: dict, result: dict) -> dict:
    return {
        "key": item["key"],
        "codigo": item["codigo"],
        "status": result.get("status", ""),
        "excel_name": item.get("excel_name", ""),
        "local_path": item.get("local_path", ""),
        "rows": result.get("rows", 0),
        "error": result.get("error", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    main()
