import argparse
import asyncio
import csv
import time
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.sharepoint_client import SharePointClient, normalize_offer_code  # noqa: E402


FIELDS = [
    "codigo",
    "folder_name",
    "total_files",
    "pdf_count",
    "zip_count",
    "office_count",
    "candidate_count",
    "top_candidates",
    "zip_files",
    "office_files",
    "error",
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Audita ofertas no_pdf buscando documentos escondidos.")
    parser.add_argument("--manifest", default="storage/commercial_offers_latest/manifest.csv")
    parser.add_argument("--out", default="storage/commercial_offers_latest/no_pdf_audit_o2000.csv")
    parser.add_argument("--min-code", type=int, default=2000)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    manifest_path = settings.resolve_path(args.manifest)
    out_path = settings.resolve_path(args.out)
    rows = load_manifest(manifest_path)
    targets = [
        row
        for row in rows
        if row.get("status") == "no_pdf"
        and row.get("codigo", "").startswith("O-")
        and int(row["codigo"].split("-")[1]) >= args.min_code
    ]
    if args.limit:
        targets = targets[: args.limit]

    sp = SharePointClient()
    headers = sp._headers()
    site_url = settings.site_url_ofertas or settings.site_url_proyectos
    results: list[dict] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=90) as client:
        drive_id = await sp._default_drive_id(client, headers, site_url)
        root = await sp._item_by_path(client, headers, drive_id, "01 Ofertas")
        offer_folders = await sp._children(client, headers, drive_id, root["id"])
        by_code = {normalize_offer_code(item.get("name", "")): item for item in offer_folders if item.get("folder")}

        for index, row in enumerate(targets, start=1):
            codigo = row["codigo"]
            result = {
                "codigo": codigo,
                "folder_name": row.get("folder_name", ""),
                "total_files": 0,
                "pdf_count": 0,
                "zip_count": 0,
                "office_count": 0,
                "candidate_count": 0,
                "top_candidates": "",
                "zip_files": "",
                "office_files": "",
                "error": "",
            }
            try:
                folder = by_code.get(codigo)
                if not folder:
                    result["error"] = "folder_not_found"
                else:
                    files = await list_descendant_files(sp, client, headers, drive_id, folder["id"])
                    result.update(summarize_files(files))
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)
            save(out_path, results)
            print(f"[{index}/{len(targets)}] {codigo} pdf={result['pdf_count']} zip={result['zip_count']} office={result['office_count']} candidates={result['candidate_count']}")


async def list_descendant_files(
    sp: SharePointClient,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    drive_id: str,
    parent_id: str,
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 8,
) -> list[dict]:
    if depth > max_depth:
        return []
    items = await sp._children(client, headers, drive_id, parent_id)
    files: list[dict] = []
    for item in items:
        path = f"{prefix}/{item.get('name', '')}".strip("/")
        if item.get("file"):
            files.append({"name": item.get("name", ""), "path": path, "webUrl": item.get("webUrl", "")})
        elif item.get("folder"):
            files.extend(await list_descendant_files(sp, client, headers, drive_id, item["id"], path, depth + 1, max_depth))
    return files


def summarize_files(files: list[dict]) -> dict:
    pdfs = [file for file in files if file["name"].lower().endswith(".pdf")]
    zips = [file for file in files if file["name"].lower().endswith((".zip", ".rar", ".7z"))]
    office = [file for file in files if file["name"].lower().endswith((".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"))]
    candidates = sorted(pdfs + office + zips, key=lambda file: candidate_score(file["path"]), reverse=True)
    return {
        "total_files": len(files),
        "pdf_count": len(pdfs),
        "zip_count": len(zips),
        "office_count": len(office),
        "candidate_count": sum(1 for file in candidates if candidate_score(file["path"]) > 0),
        "top_candidates": " || ".join(file["path"] for file in candidates[:8]),
        "zip_files": " || ".join(file["path"] for file in zips[:8]),
        "office_files": " || ".join(file["path"] for file in office[:8]),
        "error": "",
    }


def candidate_score(path: str) -> int:
    text = path.lower()
    score = 0
    for token in ["oferta", "propuesta", "proposta", "tecnica", "técnica", "metodologia", "metodología", "alcance", "ot-"]:
        if token in text:
            score += 5
    for token in ["emitido", "enviado", "entregada", "rev"]:
        if token in text:
            score += 2
    for token in ["cv", "certificado", "carta excusa", "formulario", "declaracion", "declaración", "precio", "eco-", "curva s", "cronograma"]:
        if token in text:
            score -= 8
    return score


def load_manifest(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def save(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    for attempt in range(1, 6):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.5 * attempt)


if __name__ == "__main__":
    asyncio.run(main())
