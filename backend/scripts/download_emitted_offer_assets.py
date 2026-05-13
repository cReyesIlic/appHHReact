import argparse
import asyncio
import csv
import json
import re
import sys
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.llm import LlmService  # noqa: E402
from app.services.sharepoint_client import SharePointClient, normalize_offer_code  # noqa: E402


DOC_EXTS = (".pdf", ".xlsx", ".xlsm", ".xls", ".zip", ".rar", ".7z")
PDF_EXTS = (".pdf",)
EXCEL_EXTS = (".xlsx", ".xlsm", ".xls")
ZIP_EXTS = (".zip",)
EMITIDO_NAMES = ["02 emitido", "02 emitidos", "emitido", "emitidos"]

MANIFEST_FIELDS = [
    "codigo",
    "status",
    "folder_name",
    "pdf_count",
    "excel_count",
    "zip_count",
    "selected_pdf",
    "selected_pdf_local",
    "selected_excel",
    "selected_excel_local",
    "zip_assets",
    "error",
    "updated_at",
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga PDFs tecnicos y Excel HH solo desde 03 Oferta/Emitido(s).")
    parser.add_argument("--out", default="storage/emitted_offer_assets")
    parser.add_argument("--codes", default="", help="Codigos O-XXXX separados por coma.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=1)
    parser.add_argument("--max-excels", type=int, default=2)
    parser.add_argument("--max-zip-assets", type=int, default=4)
    args = parser.parse_args()

    out_dir = settings.resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.csv"
    log_path = out_dir / "download.log"
    existing = load_manifest(manifest_path)

    sp = SharePointClient()
    llm = LlmService()
    folders = await resolve_folders(sp, args.codes, args.limit)

    rows: list[dict] = []
    write_log(log_path, f"Inicio assets emitidos folders={len(folders)} out={out_dir}")
    async with httpx.AsyncClient(timeout=120) as http:
        for index, folder in enumerate(folders, start=1):
            codigo = folder["codigo"]
            if args.skip_existing and existing.get(codigo, {}).get("status") == "ok":
                rows.append(existing[codigo])
                write_log(log_path, f"[{index}/{len(folders)}] {codigo} skip existing")
                continue

            row = base_row(codigo, folder)
            try:
                files = await list_emitido_files(sp, http, folder["item"])
                pdfs = [file for file in files if file["name"].lower().endswith(PDF_EXTS)]
                excels = [file for file in files if file["name"].lower().endswith(EXCEL_EXTS)]
                zips = [file for file in files if file["name"].lower().endswith(ZIP_EXTS)]
                row["pdf_count"] = len(pdfs)
                row["excel_count"] = len(excels)
                row["zip_count"] = len(zips)

                selected_pdfs = await download_selected_pdfs(sp, llm, http, out_dir, codigo, pdfs, args.max_pdfs)
                selected_excels = await download_selected_excels(sp, http, out_dir, codigo, excels, args.max_excels)
                zip_assets = await download_zip_assets(sp, llm, http, out_dir, codigo, zips, args.max_zip_assets)

                row.update(
                    {
                        "status": "ok" if selected_pdfs or selected_excels or zip_assets else "no_assets",
                        "selected_pdf": " || ".join(item["source"] for item in selected_pdfs),
                        "selected_pdf_local": " || ".join(item["local"] for item in selected_pdfs),
                        "selected_excel": " || ".join(item["source"] for item in selected_excels),
                        "selected_excel_local": " || ".join(item["local"] for item in selected_excels),
                        "zip_assets": json.dumps(zip_assets, ensure_ascii=False),
                        "updated_at": now(),
                    }
                )
                write_log(
                    log_path,
                    f"[{index}/{len(folders)}] {codigo} {row['status']} pdf={len(selected_pdfs)}/{len(pdfs)} excel={len(selected_excels)}/{len(excels)} zip_assets={len(zip_assets)}",
                )
            except Exception as exc:
                row.update({"status": "error", "error": str(exc), "updated_at": now()})
                write_log(log_path, f"[{index}/{len(folders)}] {codigo} error={exc}")
            rows.append(row)
            save_manifest(manifest_path, merge(existing, rows))

    final_rows = merge(existing, rows)
    save_manifest(manifest_path, final_rows)
    write_log(log_path, f"Fin assets emitidos {summarize(final_rows)}")


async def resolve_folders(sp: SharePointClient, codes: str, limit: int) -> list[dict]:
    headers = sp._headers()
    site_url = settings.site_url_ofertas or settings.site_url_proyectos
    async with httpx.AsyncClient(timeout=120) as client:
        drive_id = await sp._default_drive_id(client, headers, site_url)
        root = await sp._item_by_path(client, headers, drive_id, "01 Ofertas")
        children = await sp._children(client, headers, drive_id, root["id"])
    all_folders = []
    requested = {code.strip().upper() for code in codes.split(",") if code.strip()}
    for child in children:
        codigo = normalize_offer_code(child.get("name", ""))
        if not codigo or not child.get("folder"):
            continue
        if requested and codigo not in requested:
            continue
        all_folders.append({"codigo": codigo, "name": child.get("name", ""), "webUrl": child.get("webUrl", ""), "item": child})
        if limit and len(all_folders) >= limit:
            break
    return all_folders


async def list_emitido_files(sp: SharePointClient, client: httpx.AsyncClient, offer: dict) -> list[dict]:
    headers = sp._headers()
    site_url = settings.site_url_ofertas or settings.site_url_proyectos
    drive_id = await sp._default_drive_id(client, headers, site_url)
    proposal = await sp._find_child_by_names(client, headers, drive_id, offer["id"], ["03 Oferta", "03 Propuesta", "Oferta", "Propuesta"])
    if not proposal:
        return []
    emitidos = await find_emitido_folders(sp, client, headers, drive_id, proposal["id"])
    files: list[dict] = []
    for emitido in emitidos:
        files.extend(await list_descendant_files(sp, client, headers, drive_id, emitido["id"], emitido["name"], max_depth=7))
    return [file for file in files if file["name"].lower().endswith(DOC_EXTS)]


async def find_emitido_folders(sp: SharePointClient, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, proposal_id: str) -> list[dict]:
    children = await sp._children(client, headers, drive_id, proposal_id)
    emitidos = [child for child in children if child.get("folder") and any(token in sp._norm(child.get("name", "")) for token in EMITIDO_NAMES)]
    return sorted(emitidos, key=lambda item: emitido_score(sp._norm(item.get("name", ""))), reverse=True)


async def list_descendant_files(
    sp: SharePointClient,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    drive_id: str,
    parent_id: str,
    prefix: str,
    max_depth: int,
    depth: int = 0,
) -> list[dict]:
    if depth > max_depth:
        return []
    files: list[dict] = []
    for item in await sp._children(client, headers, drive_id, parent_id):
        path = f"{prefix}/{item.get('name', '')}".strip("/")
        if item.get("file"):
            files.append({"name": item.get("name", ""), "path": path, "webUrl": item.get("webUrl", ""), "downloadUrl": item.get("@microsoft.graph.downloadUrl")})
        elif item.get("folder"):
            files.extend(await list_descendant_files(sp, client, headers, drive_id, item["id"], path, max_depth, depth + 1))
    return files


async def download_selected_pdfs(sp: SharePointClient, llm: LlmService, client: httpx.AsyncClient, out_dir: Path, codigo: str, pdfs: list[dict], max_items: int) -> list[dict]:
    selected = []
    for pdf in sorted(pdfs, key=lambda item: pdf_score(codigo, item["path"]), reverse=True):
        if len(selected) >= max_items:
            break
        content = await download_file(sp, client, pdf)
        first_page = sp.extract_first_pages_text(content, pages=1)
        classification = await llm.classify_offer_pdf(codigo, pdf["name"], first_page)
        if classification.get("is_offer") and classification.get("confidence", 0) >= 0.45:
            local = save_bytes(out_dir / "pdf" / codigo, pdf["name"], content)
            selected.append({"source": pdf["path"], "local": str(local), "reason": classification.get("reason", "")})
    return selected


async def download_selected_excels(sp: SharePointClient, client: httpx.AsyncClient, out_dir: Path, codigo: str, excels: list[dict], max_items: int) -> list[dict]:
    selected = []
    for excel in sorted(excels, key=lambda item: excel_score(codigo, item["path"]), reverse=True):
        if len(selected) >= max_items:
            break
        if excel_score(codigo, excel["path"]) <= 0:
            continue
        content = await download_file(sp, client, excel)
        local = save_bytes(out_dir / "excel" / codigo, excel["name"], content)
        selected.append({"source": excel["path"], "local": str(local)})
    return selected


async def download_zip_assets(sp: SharePointClient, llm: LlmService, client: httpx.AsyncClient, out_dir: Path, codigo: str, zips: list[dict], max_items: int) -> list[dict]:
    assets = []
    for item in sorted(zips, key=lambda file: zip_score(codigo, file["path"]), reverse=True):
        if len(assets) >= max_items:
            break
        if zip_score(codigo, item["path"]) <= 0:
            continue
        content = await download_file(sp, client, item)
        zip_local = save_bytes(out_dir / "zip" / codigo, item["name"], content)
        extracted = extract_zip_assets(content, out_dir / "zip_extracted" / codigo / safe_stem(item["name"]), codigo, max_items - len(assets))
        assets.append({"source": item["path"], "local": str(zip_local), "extracted": extracted})
    return assets


def extract_zip_assets(content: bytes, out_dir: Path, codigo: str, remaining: int) -> list[dict]:
    extracted = []
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            candidates = sorted(
                [name for name in names if name.lower().endswith(PDF_EXTS + EXCEL_EXTS)],
                key=lambda name: max(pdf_score(codigo, name), excel_score(codigo, name)),
                reverse=True,
            )
            for name in candidates:
                if len(extracted) >= remaining:
                    break
                if is_rejected_zip_member(name):
                    continue
                if max(pdf_score(codigo, name), excel_score(codigo, name)) <= 0:
                    continue
                data = archive.read(name)
                local = save_bytes(out_dir, Path(name).name, data)
                extracted.append({"source": name, "local": str(local)})
    except Exception as exc:
        extracted.append({"error": str(exc)})
    return extracted


def is_rejected_zip_member(name: str) -> bool:
    text = normalize_text(name)
    rejected = [
        "curriculum",
        "cv ",
        "/cv",
        "\\cv",
        "certificado",
        "declaracion",
        "formulario",
        "carta",
        "exclusion",
        "exclusiones",
        "economica",
        "precio",
        "precios",
    ]
    return any(token in text for token in rejected)


async def download_file(sp: SharePointClient, client: httpx.AsyncClient, item: dict) -> bytes:
    url = item.get("downloadUrl") or item.get("@microsoft.graph.downloadUrl")
    if not url:
        raise RuntimeError(f"Archivo sin downloadUrl: {item.get('path') or item.get('name')}")
    return await sp._request_content(client, url)


def pdf_score(codigo: str, path: str) -> int:
    text = normalize_text(path)
    score = base_code_score(codigo, text)
    for token in ["oferta tecnica", "propuesta tecnica", "proposta tecnica", "prop tecnica", "ot-", "metodologia", "alcance", "tecnica rev"]:
        if token in text:
            score += 18
    for token in ["emitido", "emitidos", "rev"]:
        if token in text:
            score += 3
    for token in ["economica", "precio", "precios", "eco-", "carta", "cv", "certificado", "formulario", "declaracion", "exclusion", "cronograma", "curva"]:
        if token in text:
            score -= 20
    return score


def excel_score(codigo: str, path: str) -> int:
    text = normalize_text(path)
    score = base_code_score(codigo, text)
    for token in ["hh", "estimacion", "estimacion de horas", "horas", "entregables", "tarifa", "costos", "costo", "proyecto sh", "form tec"]:
        if token in text:
            score += 18
    for token in ["emitido", "emitidos", "interno", "rev"]:
        if token in text:
            score += 3
    for token in ["~$", "cv", "certificado", "declaracion", "carta", "eco-10", "exclusion"]:
        if token in text:
            score -= 20
    return score


def zip_score(codigo: str, path: str) -> int:
    text = normalize_text(path)
    score = base_code_score(codigo, text)
    for token in ["oferta tecnica", "propuesta tecnica", "proposta tecnica", "tecnica", "prop tecnica"]:
        if token in text:
            score += 18
    for token in ["economica", "comercial", "antecedentes", "exclusion", "exclusiones", "cv", "curriculum"]:
        if token in text:
            score -= 40
    return score


def base_code_score(codigo: str, text: str) -> int:
    return 12 if codigo.lower() in text or codigo.lower().replace("-", "") in text else 0


def emitido_score(name: str) -> int:
    score = 0
    if "02" in name:
        score += 5
    if "emitido" in name or "emitidos" in name:
        score += 10
    return score


def normalize_text(value: str) -> str:
    return (
        value.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ã", "a")
        .replace("ç", "c")
    )


def save_bytes(folder: Path, name: str, content: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name(name)
    path.write_bytes(content)
    return path


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "archivo"


def safe_stem(name: str) -> str:
    return safe_name(Path(name).stem)


def base_row(codigo: str, folder: dict) -> dict:
    return {
        "codigo": codigo,
        "status": "pending",
        "folder_name": folder.get("name", ""),
        "pdf_count": 0,
        "excel_count": 0,
        "zip_count": 0,
        "selected_pdf": "",
        "selected_pdf_local": "",
        "selected_excel": "",
        "selected_excel_local": "",
        "zip_assets": "",
        "error": "",
        "updated_at": now(),
    }


def load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return {row["codigo"]: row for row in csv.DictReader(file)}


def save_manifest(path: Path, rows_by_code: dict[str, dict]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in sorted(rows_by_code.values(), key=lambda item: item["codigo"]):
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
    tmp_path.replace(path)


def merge(existing: dict[str, dict], rows: list[dict]) -> dict[str, dict]:
    merged = dict(existing)
    for row in rows:
        merged[row["codigo"]] = row
    return merged


def summarize(rows_by_code: dict[str, dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows_by_code.values():
        counts[row.get("status", "unknown")] = counts.get(row.get("status", "unknown"), 0) + 1
    return {"total": len(rows_by_code), "counts": counts, "updated_at": now()}


def write_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{now()} {message}\n")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    asyncio.run(main())
