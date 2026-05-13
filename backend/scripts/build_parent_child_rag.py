import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.rag.parent_child import ParentChildIndexer  # noqa: E402
from app.services.liteparse_client import LiteParseClient  # noqa: E402
from app.services.master_repository import MasterRepository  # noqa: E402
from app.services.proposal_taxonomy import enrich_metadata  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Construye RAG parent-child desde PDFs descargados usando LiteParse.")
    parser.add_argument("--manifest", default="storage/commercial_offers_latest/manifest.csv")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--codes", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--liteparse-url", default="http://127.0.0.1:8787")
    parser.add_argument("--state", default="storage/rag_parent_child_manifest.csv")
    args = parser.parse_args()

    liteparse = LiteParseClient(args.liteparse_url)
    indexer = ParentChildIndexer()
    master = MasterRepository()
    state_path = settings.resolve_path(args.state)
    state = {row["codigo"]: row for row in read_csv(state_path)}
    rows = expand_manifest_rows(read_csv(settings.resolve_path(args.manifest)))
    if args.codes.strip():
        wanted = {code.strip().upper() for code in args.codes.split(",") if code.strip()}
        rows = [row for row in rows if row.get("codigo", "").upper() in wanted]

    processed = []
    for row in rows:
        if args.limit and len(processed) >= args.limit:
            break
        codigo = row["codigo"].upper()
        if not args.force and state.get(codigo, {}).get("status") == "ok":
            continue
        try:
            local_path = Path(row["local_path"])
            metadata = make_metadata(row, master)
            wiki_detail = settings.resolve_path(f"storage/llm_wiki/proposals/{codigo}.md")
            if wiki_detail.exists():
                result = indexer.index_markdown(codigo, wiki_detail.read_text(encoding="utf-8"), metadata)
            else:
                parse_result = await liteparse.parse_file(local_path)
                result = indexer.index_parse_result(codigo, parse_result, metadata)
            processed.append(status_row(codigo, "ok", row, "", result))
        except Exception as exc:
            processed.append(status_row(codigo, "error", row, str(exc), {}))
        save_csv(state_path, merge(state, processed))

    save_csv(state_path, merge(state, processed))
    print(json.dumps({"processed": len(processed), "state": str(state_path)}, ensure_ascii=False, indent=2))


def make_metadata(row: dict, master: MasterRepository) -> dict:
    codigo = row["codigo"].upper()
    master_rows = master.search(codigo=codigo, limit=1)
    master_row = master_rows[0] if master_rows else {}
    metadata = {
        "codigo": codigo,
        "tipo_documento": "oferta_tecnica",
        "archivo_nombre": row.get("pdf_name"),
        "source_path": row.get("local_path"),
        "url": row.get("web_url"),
        "parser": "liteparse",
        "cliente": master_row.get("cliente_directo"),
        "cliente_final": master_row.get("cliente_final"),
        "titulo": master_row.get("titulo") or row.get("pdf_name"),
        "estado": master_row.get("estado"),
        "tipo_servicio": master_row.get("tipo_servicio"),
        "fecha_recepcion": master_row.get("fecha_recep") or master_row.get("fecha_recepcion"),
    }
    return enrich_metadata(metadata)


def expand_manifest_rows(rows: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for row in rows:
        if row.get("status") != "ok":
            continue
        if row.get("local_path"):
            if Path(row["local_path"]).exists():
                expanded.append(row)
            continue
        direct_pdfs = split_multi(row.get("selected_pdf_local"))
        direct_names = split_multi(row.get("selected_pdf"))
        for index, path in enumerate(direct_pdfs):
            if not Path(path).exists():
                continue
            expanded.append(
                {
                    **row,
                    "local_path": path,
                    "pdf_name": direct_names[index] if index < len(direct_names) else Path(path).name,
                    "web_url": "",
                }
            )
        if direct_pdfs:
            continue
        for asset in parse_zip_assets(row.get("zip_assets")):
            expanded.append(
                {
                    **row,
                    "local_path": asset["local_path"],
                    "pdf_name": asset["pdf_name"],
                    "web_url": "",
                }
            )
    return expanded


def split_multi(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split("||") if part.strip()]


def parse_zip_assets(value: str | None) -> list[dict]:
    try:
        assets = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    rows: list[dict] = []
    for asset in assets if isinstance(assets, list) else []:
        for extracted in asset.get("extracted", []) if isinstance(asset, dict) else []:
            local = extracted.get("local", "")
            source = extracted.get("source", "")
            if local.lower().endswith(".pdf") and Path(local).exists():
                rows.append({"local_path": local, "pdf_name": source or Path(local).name})
    return rows[:1]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def save_csv(path: Path, rows_by_code: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["codigo", "status", "pdf_name", "parents", "children", "error", "updated_at"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows_by_code.values(), key=lambda item: item["codigo"]):
            writer.writerow({field: row.get(field, "") for field in fields})


def merge(existing: dict[str, dict], rows: list[dict]) -> dict[str, dict]:
    merged = dict(existing)
    for row in rows:
        merged[row["codigo"]] = row
    return merged


def status_row(codigo: str, status: str, row: dict, error: str, result: dict) -> dict:
    return {
        "codigo": codigo,
        "status": status,
        "pdf_name": row.get("pdf_name", ""),
        "parents": result.get("parents", ""),
        "children": result.get("children", ""),
        "error": error,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    asyncio.run(main())
