import argparse
import asyncio
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.llm import LlmService  # noqa: E402
from app.services.sharepoint_client import SharePointClient  # noqa: E402


MANIFEST_FIELDS = [
    "codigo",
    "status",
    "folder_name",
    "pdf_name",
    "web_url",
    "local_path",
    "bytes",
    "pdfs_found",
    "error",
    "updated_at",
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga ultima oferta tecnica PDF desde Comercial/SharePoint.")
    parser.add_argument("--out", default="storage/commercial_offers_latest", help="Carpeta destino relativa al proyecto.")
    parser.add_argument("--limit", type=int, default=100000, help="Maximo de carpetas O-XXXX a revisar.")
    parser.add_argument("--codes", default="", help="Codigos separados por coma para reprocesar solo esos O-XXXX.")
    parser.add_argument("--skip-existing", action="store_true", help="No descarga PDFs ya presentes en el manifest como ok.")
    parser.add_argument("--skip-completed", action="store_true", help="Salta codigos ya resueltos como ok o no_pdf en el manifest.")
    parser.add_argument("--only-missing", action="store_true", help="Procesa solo codigos que aun no existen en el manifest.")
    parser.add_argument("--include-o0000", action="store_true", help="Incluye carpeta O-0000 Ofertas Antiguas.")
    parser.add_argument("--retry-errors", action="store_true", help="Reprocesa solo codigos en error del manifest existente.")
    parser.add_argument("--retry-transient-only", action="store_true", help="Con --retry-errors, omite errores permanentes conocidos como 422.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Intentos por codigo ante fallos transitorios.")
    args = parser.parse_args()

    client = SharePointClient()
    llm = LlmService()
    out_dir = settings.resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.csv"
    log_path = out_dir / "download.log"

    existing = load_manifest(manifest_path)
    if args.codes.strip():
        folders = [{"codigo": code.strip().upper(), "name": code.strip().upper(), "webUrl": ""} for code in args.codes.split(",") if code.strip()]
    elif args.retry_errors:
        folders = [
            {"codigo": row["codigo"], "name": row.get("folder_name") or row["codigo"], "webUrl": row.get("web_url", "")}
            for row in existing.values()
            if row.get("status") == "error"
            and (not args.retry_transient_only or is_transient_error(row.get("error", "")) or "422 unprocessable entity" not in row.get("error", "").lower())
        ]
    else:
        folders = await client.list_offer_folders(limit=args.limit)
    if not args.include_o0000:
        folders = [folder for folder in folders if folder["codigo"] != "O-0000"]

    write_log(log_path, f"Inicio descarga. folders={len(folders)} out={out_dir}")
    rows = []
    for idx, folder in enumerate(folders, start=1):
        codigo = folder["codigo"]
        if args.only_missing and codigo in existing:
            rows.append(existing[codigo])
            write_log(log_path, f"[{idx}/{len(folders)}] {codigo} skip known")
            continue
        if args.skip_completed and existing.get(codigo, {}).get("status") in {"ok", "no_pdf"}:
            rows.append(existing[codigo])
            write_log(log_path, f"[{idx}/{len(folders)}] {codigo} skip completed")
            continue
        if args.skip_existing and existing.get(codigo, {}).get("status") == "ok":
            rows.append(existing[codigo])
            write_log(log_path, f"[{idx}/{len(folders)}] {codigo} skip existing")
            continue

        row = {
            "codigo": codigo,
            "status": "pending",
            "folder_name": folder.get("name", ""),
            "pdf_name": "",
            "web_url": folder.get("webUrl", ""),
            "local_path": "",
            "bytes": 0,
            "pdfs_found": 0,
            "error": "",
            "updated_at": now(),
        }
        for attempt in range(1, args.max_attempts + 1):
            try:
                pdfs = await client.list_pdfs(codigo)
                row["pdfs_found"] = len(pdfs)
                candidates = sort_pdfs(client, pdfs, codigo)
                accepted = None
                rejected = []
                for candidate in candidates:
                    content = await client.download_pdf(candidate)
                    first_page = client.extract_first_pages_text(content, pages=1)
                    classification = await llm.classify_offer_pdf(codigo, candidate.get("name", ""), first_page)
                    if classification.get("is_offer") and classification.get("confidence", 0) >= 0.55:
                        accepted = (candidate, content, classification)
                        break
                    rejected.append({"name": candidate.get("name", ""), **classification})

                if accepted is None:
                    row["status"] = "no_pdf"
                    row["error"] = "No se encontro PDF clasificado como oferta tecnica. Rechazados: " + json.dumps(rejected[:5], ensure_ascii=False)
                    rows.append(row)
                    write_log(log_path, f"[{idx}/{len(folders)}] {codigo} no_pdf")
                    save_manifest(manifest_path, merge(existing, rows))
                    break

                latest, content, classification = accepted
                local_path = save_latest(out_dir, codigo, latest.get("name", "oferta.pdf"), content)
                row.update(
                    {
                        "status": "ok",
                        "pdf_name": latest.get("name", ""),
                        "web_url": latest.get("webUrl", ""),
                        "local_path": str(local_path),
                        "bytes": len(content),
                        "error": classification.get("reason", ""),
                        "updated_at": now(),
                    }
                )
                rows.append(row)
                write_log(log_path, f"[{idx}/{len(folders)}] {codigo} ok bytes={len(content)} pdf={row['pdf_name']}")
                break
            except Exception as exc:
                error = str(exc)
                if attempt < args.max_attempts and is_transient_error(error):
                    wait_seconds = min(2**attempt, 20)
                    write_log(log_path, f"[{idx}/{len(folders)}] {codigo} retry {attempt}/{args.max_attempts} wait={wait_seconds}s error={error}")
                    await asyncio.sleep(wait_seconds)
                    continue
                row.update({"status": "error", "error": error, "updated_at": now()})
                rows.append(row)
                write_log(log_path, f"[{idx}/{len(folders)}] {codigo} error={error}")
                break

        save_manifest(manifest_path, merge(existing, rows))

    final_rows = merge(existing, rows)
    save_manifest(manifest_path, final_rows)
    summary = summarize(final_rows)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_log(log_path, f"Fin descarga. {summary}")


def save_latest(out_dir: Path, codigo: str, pdf_name: str, content: bytes) -> Path:
    safe_name = SharePointClient().save_pdf_locally(codigo, pdf_name, content).name
    folder = out_dir / codigo
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / safe_name
    path.write_bytes(content)
    return path


def sort_pdfs(client: SharePointClient, pdfs: list[dict], codigo: str = "") -> list[dict]:
    def score(pdf: dict) -> tuple[int, int, str]:
        selected = client.select_latest_pdf([pdf])
        name = (pdf.get("name") or "").lower()
        name_score = 0
        code_tokens = [codigo.lower(), codigo.lower().replace("-", "")]
        if any(token and token in name for token in code_tokens):
            name_score += 18
        for token in ["oferta tecnica", "oferta técnica", "propuesta tecnica", "propuesta técnica", "proposta", "oferta"]:
            if token in name:
                name_score += 10
        for token in ["programa de ingenier", "antecedentes tecnic", "antecedentes técnic"]:
            if token in name:
                name_score -= 6
        for token in [
            "oferta de precios",
            "precio",
            "precios",
            "eco-",
            "economica",
            "económica",
            "cotizacion",
            "cotización",
            "carta",
            "form.",
            "formulario",
            "declaracion",
            "declaración",
            "exclusion",
            "exclusión",
            "exclusiones",
            "aclaracion",
            "aclaración",
            "cronograma",
            "programa",
            "perfil del personal",
            "experiencia en trabajos",
            "plan de aseguramiento",
            "tabla resumen",
            "cv",
            "curriculum",
            "certificado",
            "anexo",
        ]:
            if token in name:
                name_score -= 20
        revs = [int(match) for match in __import__("re").findall(r"(?:rev\.?\s*|rev_?)(\d+)", name)]
        rev = max(revs) if revs else 0
        return name_score, rev, selected.get("lastModifiedDateTime", "") if selected else ""

    return sorted(pdfs, key=score, reverse=True)


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


def is_transient_error(error: str) -> bool:
    text = error.lower()
    transient_markers = [
        "nameresolutionerror",
        "failed to resolve",
        "timed out",
        "timeout",
        "remote protocol",
        "server disconnected",
        "503 service unavailable",
        "502 bad gateway",
        "504 gateway timeout",
        "429 too many requests",
        "401 unauthorized",
    ]
    if any(marker in text for marker in transient_markers):
        return True
    status = re.search(r"(?:client|server) error '(\d{3})", text)
    return bool(status and status.group(1) in {"401", "429", "500", "502", "503", "504"})


def write_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{now()} {message}\n")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    asyncio.run(main())
