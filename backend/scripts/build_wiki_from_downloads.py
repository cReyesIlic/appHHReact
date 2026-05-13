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
from app.services.knowledge_extractor import KnowledgeExtractor  # noqa: E402
from app.services.knowledge_models import ProposalMetadata  # noqa: E402
from app.services.liteparse_client import LiteParseClient  # noqa: E402
from app.services.master_repository import MasterRepository  # noqa: E402
from app.services.proposal_taxonomy import enrich_metadata  # noqa: E402
from app.services.sharepoint_client import SharePointClient  # noqa: E402
from app.services.structured_wiki import StructuredWikiService  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Construye LLM Wiki incremental desde PDFs descargados.")
    parser.add_argument("--manifest", default="storage/commercial_offers_latest/manifest.csv")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--state", default="storage/wiki_ingestion_manifest.csv")
    parser.add_argument("--liteparse-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()

    manifest_path = settings.resolve_path(args.manifest)
    state_path = settings.resolve_path(args.state)
    log_path = settings.resolve_path("storage/wiki_ingestion.log")
    rows = expand_manifest_rows(read_csv(manifest_path))
    state = {row["codigo"]: row for row in read_csv(state_path)}

    extractor = KnowledgeExtractor()
    liteparse = LiteParseClient(args.liteparse_url)
    sharepoint = SharePointClient()
    master = MasterRepository()
    wiki = StructuredWikiService()
    processed = []

    for row in rows:
        if args.limit and len(processed) >= args.limit:
            break
        codigo = row["codigo"]
        if not args.force and state.get(codigo, {}).get("status") == "ok":
            continue
        pdf_path = Path(row["local_path"])
        if not pdf_path.exists():
            processed.append(status_row(codigo, "missing_file", row, "PDF local no existe"))
            continue
        try:
            content = pdf_path.read_bytes()
            first_pages = await extract_first_pages(liteparse, sharepoint, pdf_path, content)
            metadata = metadata_from_row(codigo, row, master)
            knowledge = await extractor.extract(metadata, first_pages, first_pages)
            write_wiki_pages(metadata, knowledge)
            rebuild_aggregate_wiki()
            wiki.build(settings.resolve_path("storage/llm_wiki.md").read_text(encoding="utf-8"))
            processed.append(status_row(codigo, "ok", row, ""))
            log(log_path, f"{codigo} ok {row.get('pdf_name')}")
        except Exception as exc:
            processed.append(status_row(codigo, "error", row, str(exc)))
            log(log_path, f"{codigo} error {exc}")
        save_csv(state_path, merge(state, processed))

    save_csv(state_path, merge(state, processed))
    print(json.dumps({"processed": len(processed), "state": str(state_path)}, ensure_ascii=False, indent=2))


def metadata_from_row(codigo: str, row: dict, master: MasterRepository) -> ProposalMetadata:
    master_rows = master.search(codigo=codigo, limit=1)
    master_row = master_rows[0] if master_rows else {}
    return ProposalMetadata(
        codigo=codigo,
        pdf_name=row.get("pdf_name", ""),
        url=row.get("web_url"),
        local_path=row.get("local_path"),
        cliente=master_row.get("cliente_directo"),
        cliente_final=master_row.get("cliente_final"),
        titulo=master_row.get("titulo") or row.get("pdf_name"),
        estado=master_row.get("estado"),
        tipo_servicio=master_row.get("tipo_servicio"),
        fecha_recepcion=master_row.get("fecha_recep") or master_row.get("fecha_recepcion"),
    )


async def extract_first_pages(liteparse: LiteParseClient, sharepoint: SharePointClient, pdf_path: Path, content: bytes) -> str:
    try:
        parsed = await liteparse.parse_file(pdf_path)
        pages = parsed.get("pages") or []
        page_texts = []
        for index, page in enumerate(pages[:5], start=1):
            text = page.get("text") or ""
            if text.strip():
                page_texts.append(f"[Pagina {page.get('pageNumber') or page.get('page') or index}]\n{text}")
        if page_texts:
            return "\n\n".join(page_texts)
        if parsed.get("text"):
            return str(parsed["text"])[:18000]
    except Exception:
        pass
    return sharepoint.extract_first_pages_text(content, pages=5)


def render_markdown(metadata: ProposalMetadata, knowledge) -> str:
    def bullets(items):
        return "\n".join(f"- {item}" for item in items) if items else "- No identificado en primeras 5 paginas"

    meta = enrich_metadata(metadata.model_dump())
    estado_info = meta.get("estado_info") or {}
    servicio_info = meta.get("tipo_servicio_info") or []
    entidades = meta.get("entidades_taxonomia") or {}

    return f"""### Metadata
- Codigo: {metadata.codigo}
- Cliente: {metadata.cliente or 'No data'}
- Cliente final: {metadata.cliente_final or 'No data'}
- Estado: {metadata.estado or 'No data'}
- Estado normalizado: {estado_info.get('label') or 'No data'}
- Estado categoria: {meta.get('estado_categoria') or 'desconocida'}
- Propuesta ganada: {meta.get('propuesta_ganada')}
- Propuesta perdida: {meta.get('propuesta_perdida')}
- Tipo servicio: {metadata.tipo_servicio or 'No data'}
- Tipo servicio normalizado: {json.dumps(servicio_info, ensure_ascii=False)}
- PDF: {metadata.pdf_name}
- URL: {metadata.url or 'No data'}

### Entidades normalizadas
```json
{json.dumps(entidades, ensure_ascii=False, indent=2)}
```

### Resumen ejecutivo
{knowledge.resumen_ejecutivo or 'No identificado en primeras 5 paginas'}

### Objetivo
{knowledge.objetivo or 'No identificado en primeras 5 paginas'}

### Alcance
{bullets(knowledge.alcance)}

### Entregables
{bullets(knowledge.entregables)}

### Disciplinas
{bullets(knowledge.disciplinas)}

### Equipos y sistemas
{bullets(knowledge.equipos_sistemas)}

### Criterios de busqueda
{bullets(knowledge.criterios_busqueda or knowledge.keywords)}

### Util para
{bullets(knowledge.util_para)}

### Limitaciones
{bullets(knowledge.riesgos_limitaciones)}
"""


def write_wiki_pages(metadata: ProposalMetadata, knowledge) -> None:
    base = settings.resolve_path("storage/llm_wiki")
    proposal_dir = base / "proposals"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    detail = proposal_dir / f"{metadata.codigo}.md"
    meta = enrich_metadata(metadata.model_dump())
    frontmatter = {
        "codigo": metadata.codigo,
        "cliente": metadata.cliente,
        "cliente_final": metadata.cliente_final,
        "estado": metadata.estado,
        "estado_categoria": meta.get("estado_categoria"),
        "tipo_servicio": metadata.tipo_servicio,
        "tipo_documento": "oferta_tecnica",
        "fuente": metadata.local_path,
        "metadata_version": "proposal_taxonomy_v1",
    }
    detail.write_text(
        "---\n"
        + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items())
        + "\n---\n\n"
        + f"# {metadata.codigo} - {metadata.titulo or metadata.pdf_name}\n\n## Detalle estructurado\n\n{render_markdown(metadata, knowledge)}",
        encoding="utf-8",
    )
    index_path = base / "index.md"
    summaries = read_existing_summaries(index_path)
    summaries[metadata.codigo] = {
        "codigo": metadata.codigo,
        "titulo": metadata.titulo or metadata.pdf_name,
        "cliente": metadata.cliente or "No data",
        "estado": metadata.estado or "No data",
        "summary": knowledge.resumen_ejecutivo[:500],
        "path": f"proposals/{metadata.codigo}.md",
    }
    lines = ["# LLM Wiki SHIMIN", "", "## Indice de propuestas", ""]
    for code in sorted(summaries):
        item = summaries[code]
        lines.extend(
            [
                f"### [{item['codigo']} - {item['titulo']}]({item['path']})",
                f"- Cliente: {item['cliente']}",
                f"- Estado: {item['estado']}",
                f"- Resumen: {item['summary'] or 'No data'}",
                "",
            ]
        )
    index_path.write_text("\n".join(lines), encoding="utf-8")


def rebuild_aggregate_wiki() -> None:
    base = settings.resolve_path("storage/llm_wiki")
    index_path = base / "index.md"
    proposal_dir = base / "proposals"
    parts = [index_path.read_text(encoding="utf-8") if index_path.exists() else "# LLM Wiki SHIMIN\n"]
    for path in sorted(proposal_dir.glob("O-*.md")) if proposal_dir.exists() else []:
        parts.append(f"\n\n<!-- proposal:{path.stem} -->\n" + path.read_text(encoding="utf-8"))
    settings.resolve_path("storage/llm_wiki.md").write_text("\n".join(parts), encoding="utf-8")


def read_existing_summaries(index_path: Path) -> dict:
    # Lightweight parser for the generated index. Detail pages remain source of truth.
    summaries = {}
    if not index_path.exists():
        return summaries
    current = None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### ["):
            label = line.split("[", 1)[1].split("]", 1)[0]
            code, _, title = label.partition(" - ")
            current = {"codigo": code, "titulo": title, "cliente": "No data", "estado": "No data", "summary": "", "path": f"proposals/{code}.md"}
            summaries[code] = current
        elif current and line.startswith("- Cliente:"):
            current["cliente"] = line.split(":", 1)[1].strip()
        elif current and line.startswith("- Estado:"):
            current["estado"] = line.split(":", 1)[1].strip()
        elif current and line.startswith("- Resumen:"):
            current["summary"] = line.split(":", 1)[1].strip()
    return summaries


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
    fields = ["codigo", "status", "pdf_name", "local_path", "error", "updated_at"]
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


def status_row(codigo: str, status: str, source: dict, error: str) -> dict:
    return {
        "codigo": codigo,
        "status": status,
        "pdf_name": source.get("pdf_name", ""),
        "local_path": source.get("local_path", ""),
        "error": error,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


if __name__ == "__main__":
    asyncio.run(main())
