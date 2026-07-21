import re
import asyncio
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import msal
from PyPDF2 import PdfReader
from rapidfuzz import fuzz

from app.core.config import settings
from app.services.rag_client import RagClient


GRAPH = "https://graph.microsoft.com/v1.0"


class SharePointClient:
    def __init__(self) -> None:
        self.rag = RagClient()
        self._cached_token: str | None = None
        self._token_expires_at = 0.0

    async def fetch_relevant_pdf_text(self, codes: list[str], question: str) -> list[dict]:
        if not self._configured():
            return []
        headers = self._headers()
        contexts: list[dict] = []
        async with httpx.AsyncClient(timeout=60) as client:
            for code in codes:
                pdfs = await self._find_pdfs(client, headers, code)
                for pdf in pdfs[:1]:
                    download_url = pdf.get("@microsoft.graph.downloadUrl")
                    if not download_url:
                        continue
                    content = await self._request_content(client, download_url)
                    text = await self.rag.parse_pdf_bytes(pdf["name"], content)
                    if not text:
                        text = self._extract_pdf_text(content)
                    contexts.append({"codigo": code, "name": pdf["name"], "url": pdf.get("webUrl"), "text": text[:20000]})
        return contexts

    async def list_pdfs(self, code: str) -> list[dict]:
        if not self._configured():
            return []
        headers = self._headers()
        async with httpx.AsyncClient(timeout=60) as client:
            return await self._find_pdfs(client, headers, code)

    async def list_offer_folders(self, limit: int = 100) -> list[dict]:
        if not self._configured():
            return []
        headers = self._headers()
        site_url = settings.site_url_ofertas or settings.site_url_proyectos
        if not site_url:
            return []
        async with httpx.AsyncClient(timeout=90) as client:
            drive_id = await self._default_drive_id(client, headers, site_url)
            root = await self._item_by_path(client, headers, drive_id, "01 Ofertas")
            children = await self._children(client, headers, drive_id, root["id"])
        folders = []
        for child in children:
            code = normalize_offer_code(child.get("name", ""))
            if child.get("folder") and code:
                folders.append({"codigo": code, "name": child.get("name"), "webUrl": child.get("webUrl")})
            if len(folders) >= limit:
                break
        return folders

    async def download_named_file(self, filename: str, site_url: str | None = None) -> tuple[bytes, dict]:
        """Busca un archivo por nombre exacto en el sitio y descarga su version vigente."""
        if not self._configured():
            raise RuntimeError("SharePoint/Graph no esta configurado")
        clean_name = str(filename or "").strip()
        if not clean_name:
            raise ValueError("Falta nombre de archivo SharePoint")
        selected_site = site_url or settings.site_url_ofertas or settings.site_url_proyectos
        if not selected_site:
            raise RuntimeError("Falta SITE_URL_OFERTAS o SITE_URL_PROYECTOS")

        headers = self._headers()
        async with httpx.AsyncClient(timeout=120) as client:
            drive_id = await self._default_drive_id(client, headers, selected_site)
            escaped = quote(clean_name.replace("'", "''"), safe="")
            search = await self._request_json(
                client,
                f"{GRAPH}/drives/{drive_id}/root/search(q='{escaped}')?$top=200",
                headers=headers,
            )
            exact = [
                item for item in search.get("value", [])
                if item.get("file") and str(item.get("name") or "").casefold() == clean_name.casefold()
            ]
            if not exact:
                raise FileNotFoundError(f"No se encontro '{clean_name}' en SharePoint")
            item = max(exact, key=lambda row: str(row.get("lastModifiedDateTime") or ""))
            if not item.get("@microsoft.graph.downloadUrl"):
                item = await self._request_json(
                    client,
                    f"{GRAPH}/drives/{drive_id}/items/{item['id']}",
                    headers=headers,
                )
            content = await self._request_content(client, item["@microsoft.graph.downloadUrl"])
        return content, {
            "name": item.get("name"),
            "item_id": item.get("id"),
            "last_modified": item.get("lastModifiedDateTime"),
            "size": item.get("size") or len(content),
            "web_url": item.get("webUrl"),
        }

    async def download_pdf(self, pdf: dict) -> bytes:
        return await self.download_file(pdf)

    async def download_file(self, item: dict) -> bytes:
        """Descarga cualquier archivo (PDF, DOCX, etc.) desde el downloadUrl de Graph."""
        download_url = item.get("@microsoft.graph.downloadUrl")
        if not download_url:
            raise RuntimeError("El archivo no trae downloadUrl de Microsoft Graph")
        async with httpx.AsyncClient(timeout=120) as client:
            return await self._request_content(client, download_url)

    async def list_emitido_files(
        self,
        code: str,
        kinds: tuple[str, ...] = (".pdf", ".docx", ".xlsx", ".xlsm", ".xls"),
    ) -> list[dict]:
        """Lista archivos emitidos (PDF/DOCX/XLSX) de la carpeta '03 Oferta/02 Emitido' de O-XXXX.

        A diferencia de `list_pdfs` (que solo trae PDFs), este método trae cualquier formato
        ofimático en la carpeta emitida. Útil cuando la propuesta SHIMIN se envió como Excel
        (ODS) o Word, no PDF.
        """
        if not self._configured():
            return []
        headers = self._headers()
        site_url = settings.site_url_ofertas or settings.site_url_proyectos
        if not site_url:
            return []
        async with httpx.AsyncClient(timeout=90) as client:
            drive_id = await self._default_drive_id(client, headers, site_url)
            root = await self._item_by_path(client, headers, drive_id, "01 Ofertas")
            offer = await self._find_child_by_code(client, headers, drive_id, root["id"], normalize_offer_code(code))
            if not offer:
                return []
            proposal = await self._find_child_by_names(client, headers, drive_id, offer["id"], ["03 Oferta", "Oferta"])
            if not proposal:
                return []
            final = await self._find_child_by_names(client, headers, drive_id, proposal["id"], ["02 Emitido", "02 Emitidos", "Emitido", "Emitidos", "Enviado"])
            if not final:
                return []
            files = await self._files_descendants(client, headers, drive_id, final["id"], kinds=kinds, max_depth=4)
        return [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "size": f.get("size") or 0,
                "webUrl": f.get("webUrl"),
                "lastModifiedDateTime": f.get("lastModifiedDateTime"),
                "eTag": f.get("eTag"),
                "kind": (f.get("name", "").lower().rsplit(".", 1)[-1] if "." in f.get("name", "") else ""),
                "@microsoft.graph.downloadUrl": f.get("@microsoft.graph.downloadUrl"),
            }
            for f in files
        ]

    async def list_offer_antecedentes(self, code: str, kinds: tuple[str, ...] = (".pdf", ".docx")) -> list[dict]:
        """Lista PDFs y DOCX dentro de la carpeta '01 Informacion Cliente' de una oferta O-XXXX.

        Busca recursivamente en subcarpetas (hasta profundidad 4). Devuelve metadata de cada archivo.
        Estos son los ANTECEDENTES del cliente: RFP, bases técnicas, especificaciones, etc.
        """
        if not self._configured():
            return []
        headers = self._headers()
        site_url = settings.site_url_ofertas or settings.site_url_proyectos
        if not site_url:
            return []
        async with httpx.AsyncClient(timeout=90) as client:
            drive_id = await self._default_drive_id(client, headers, site_url)
            root = await self._item_by_path(client, headers, drive_id, "01 Ofertas")
            offer = await self._find_child_by_code(
                client, headers, drive_id, root["id"], normalize_offer_code(code)
            )
            if not offer:
                return []
            ant = await self._find_child_by_names(
                client, headers, drive_id, offer["id"],
                ["01 Informacion Cliente", "01 Información Cliente",
                 "Informacion Cliente", "Información Cliente",
                 "01 Antecedentes", "Antecedentes"],
            )
            if not ant:
                return []
            files = await self._files_descendants(client, headers, drive_id, ant["id"], kinds=kinds, max_depth=4)
        return [
            {
                "name": f.get("name"),
                "size": (f.get("size") or 0),
                "webUrl": f.get("webUrl"),
                "id": f.get("id"),
                "kind": (f.get("name", "").lower().rsplit(".", 1)[-1] if "." in f.get("name", "") else ""),
                "downloadUrl": f.get("@microsoft.graph.downloadUrl"),
                "@microsoft.graph.downloadUrl": f.get("@microsoft.graph.downloadUrl"),
            }
            for f in files
        ]

    async def _find_pdfs(self, client: httpx.AsyncClient, headers: dict[str, str], code: str) -> list[dict]:
        normalized = code.strip().upper()
        if normalized.startswith("O"):
            return await self._find_offer_pdfs(client, headers, normalized)
        if normalized.startswith("SH"):
            return await self._find_project_pdfs(client, headers, normalized)
        return []

    async def _find_offer_pdfs(self, client: httpx.AsyncClient, headers: dict[str, str], code: str) -> list[dict]:
        site_url = settings.site_url_ofertas or settings.site_url_proyectos
        if not site_url:
            return []
        drive_id = await self._default_drive_id(client, headers, site_url)
        root = await self._item_by_path(client, headers, drive_id, "01 Ofertas")
        offer = await self._find_child_by_code(client, headers, drive_id, root["id"], normalize_offer_code(code))
        if not offer:
            return []
        proposal = await self._find_child_by_names(client, headers, drive_id, offer["id"], ["03 Oferta", "03 Propuesta", "Oferta", "Propuesta"])
        if not proposal:
            return []
        final = await self._find_child_by_names(client, headers, drive_id, proposal["id"], ["02 Emitido", "02 Emitidos", "Emitido", "Emitidos", "Enviado"])
        if not final:
            return []
        pdfs = await self._pdf_children(client, headers, drive_id, final["id"])
        if pdfs:
            return pdfs
        return await self._pdf_descendants(client, headers, drive_id, final["id"], max_depth=4)

    async def _find_project_pdfs(self, client: httpx.AsyncClient, headers: dict[str, str], code: str) -> list[dict]:
        site_url = settings.site_url_proyectos or settings.site_url_ofertas
        if not site_url:
            return []
        drive_id = await self._default_drive_id(client, headers, site_url)
        root = await self._item_by_path(client, headers, drive_id, "Proyectos")
        project = await self._find_child_by_code(client, headers, drive_id, root["id"], normalize_project_code(code))
        if not project:
            return []
        admin = await self._find_child_by_names(client, headers, drive_id, project["id"], ["02 Administración", "Administracion", "Administración"])
        if not admin:
            return []
        oferta = await self._find_child_by_names(client, headers, drive_id, admin["id"], ["05 Oferta Técnica", "Oferta Tecnica", "Oferta Técnica"])
        if not oferta:
            return []
        pdfs = await self._pdf_children(client, headers, drive_id, oferta["id"])
        if pdfs:
            return pdfs
        return await self._pdf_descendants(client, headers, drive_id, oferta["id"], max_depth=3)

    async def _default_drive_id(self, client: httpx.AsyncClient, headers: dict[str, str], site_url: str) -> str:
        site = await self._site_from_url(client, headers, site_url)
        data = await self._request_json(client, f"{GRAPH}/sites/{site['id']}/drives", headers=headers)
        drives = data.get("value", [])
        if not drives:
            raise RuntimeError("El sitio SharePoint no tiene drives disponibles")
        return drives[0]["id"]

    async def _site_from_url(self, client: httpx.AsyncClient, headers: dict[str, str], site_url: str) -> dict:
        parsed = urlparse(site_url)
        if parsed.hostname:
            hostname = parsed.hostname
            site_path = parsed.path.strip("/")
        else:
            hostname = settings.sharepoint_site
            raw_path = site_url.strip().strip("/")
            site_path = raw_path if raw_path.lower().startswith("sites/") else f"sites/{raw_path}"
        if not hostname or not site_path:
            raise RuntimeError("Falta SHAREPOINT_SITE o ruta de sitio SharePoint")
        return await self._request_json(client, f"{GRAPH}/sites/{hostname}:/{site_path}", headers=headers)

    async def _item_by_path(self, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, path: str) -> dict:
        return await self._request_json(client, f"{GRAPH}/drives/{drive_id}/root:/{path}", headers=headers)

    async def _children(self, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, item_id: str) -> list[dict]:
        url = f"{GRAPH}/drives/{drive_id}/items/{item_id}/children?$top=200"
        items: list[dict] = []
        while url:
            data = await self._request_json(client, url, headers=headers)
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    async def _find_child_by_code(self, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, parent_id: str, code: str | None) -> dict | None:
        if not code:
            return None
        children = await self._children(client, headers, drive_id, parent_id)
        exact = [child for child in children if normalize_offer_code(child["name"]) == code or normalize_project_code(child["name"]) == code]
        if exact:
            return exact[0]
        ranked = sorted(children, key=lambda child: fuzz.partial_ratio(code, child["name"].upper()), reverse=True)
        if ranked and fuzz.partial_ratio(code, ranked[0]["name"].upper()) >= 85:
            return ranked[0]
        return None

    async def _find_child_by_names(self, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, parent_id: str, names: list[str]) -> dict | None:
        children = await self._children(client, headers, drive_id, parent_id)
        targets = [self._norm(name) for name in names]
        for child in children:
            child_name = self._norm(child["name"])
            if any(target in child_name for target in targets):
                return child
        ranked = sorted(children, key=lambda child: max(fuzz.partial_ratio(self._norm(child["name"]), target) for target in targets), reverse=True)
        if ranked:
            score = max(fuzz.partial_ratio(self._norm(ranked[0]["name"]), target) for target in targets)
            if score >= 80:
                return ranked[0]
        return None

    async def _pdf_children(self, client: httpx.AsyncClient, headers: dict[str, str], drive_id: str, parent_id: str) -> list[dict]:
        children = await self._children(client, headers, drive_id, parent_id)
        return [child for child in children if child.get("file") and child["name"].lower().endswith(".pdf")]

    async def _pdf_descendants(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        drive_id: str,
        parent_id: str,
        max_depth: int = 3,
        depth: int = 0,
    ) -> list[dict]:
        if depth > max_depth:
            return []
        children = await self._children(client, headers, drive_id, parent_id)
        pdfs = [child for child in children if child.get("file") and child["name"].lower().endswith(".pdf")]
        for child in children:
            if child.get("folder"):
                pdfs.extend(await self._pdf_descendants(client, headers, drive_id, child["id"], max_depth, depth + 1))
        return pdfs

    async def _files_descendants(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        drive_id: str,
        parent_id: str,
        kinds: tuple[str, ...] = (".pdf", ".docx"),
        max_depth: int = 4,
        depth: int = 0,
    ) -> list[dict]:
        """Variante genérica que acepta múltiples extensiones."""
        if depth > max_depth:
            return []
        children = await self._children(client, headers, drive_id, parent_id)
        kinds = tuple(k.lower() for k in kinds)
        files = [
            child for child in children
            if child.get("file") and child["name"].lower().endswith(kinds)
        ]
        for child in children:
            if child.get("folder"):
                files.extend(
                    await self._files_descendants(
                        client, headers, drive_id, child["id"],
                        kinds=kinds, max_depth=max_depth, depth=depth + 1,
                    )
                )
        return files

    def _extract_pdf_text(self, content: bytes) -> str:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def extract_first_pages_text(self, content: bytes, pages: int = 5) -> str:
        try:
            reader = PdfReader(BytesIO(content))
            selected = reader.pages[: min(pages, len(reader.pages))]
            return "\n".join(page.extract_text() or "" for page in selected)
        except Exception:
            return ""

    def extract_full_text(self, content: bytes) -> str:
        try:
            return self._extract_pdf_text(content)
        except Exception:
            return ""

    def select_latest_pdf(self, pdfs: list[dict]) -> dict | None:
        if not pdfs:
            return None

        def score(pdf: dict) -> tuple[int, str]:
            name = pdf.get("name", "")
            revs = [int(match) for match in re.findall(r"(?:rev\.?\s*|rev_?)(\d+)", name.lower())]
            rev = max(revs) if revs else 0
            modified = pdf.get("lastModifiedDateTime") or ""
            return rev, modified

        return sorted(pdfs, key=score, reverse=True)[0]

    def save_pdf_locally(self, codigo: str, pdf_name: str, content: bytes) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", pdf_name).strip()
        path = settings.resolve_path(f"storage/proposals/{codigo.upper()}/{safe_name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    async def _request_json(self, client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> dict:
        response = await self._request(client, url, headers=headers)
        return response.json()

    async def _request_content(self, client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None) -> bytes:
        response = await self._request(client, url, headers=headers)
        return response.content

    async def _request(self, client: httpx.AsyncClient, url: str, headers: dict[str, str] | None = None, attempts: int = 4) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 401 and headers is not None and attempt < attempts:
                    self._cached_token = None
                    headers["Authorization"] = f"Bearer {self._token()}"
                    await asyncio.sleep(1)
                    continue
                if response.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                    await asyncio.sleep(min(2**attempt, 15))
                    continue
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                await asyncio.sleep(min(2**attempt, 15))
        if last_exc:
            raise last_exc
        raise RuntimeError(f"No se pudo completar request SharePoint: {url}")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _token(self) -> str:
        if self._cached_token and time.time() < self._token_expires_at - 300:
            return self._cached_token
        result = {}
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                app = msal.ConfidentialClientApplication(
                    settings.client_id,
                    authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
                    client_credential=settings.client_secret,
                )
                result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
                break
            except Exception as exc:
                last_error = exc
                if attempt >= 3:
                    raise
                time.sleep(min(2**attempt, 10))
        token = result.get("access_token")
        if not token:
            if last_error:
                raise RuntimeError(f"No se pudo obtener token Graph: {last_error}")
            raise RuntimeError(f"No se pudo obtener token Graph: {result.get('error_description')}")
        self._cached_token = token
        self._token_expires_at = time.time() + int(result.get("expires_in", 3600))
        return token

    def _configured(self) -> bool:
        return all([settings.tenant_id, settings.client_id, settings.client_secret])

    def _norm(self, value: str) -> str:
        return value.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def normalize_offer_code(value: str) -> str | None:
    match = re.search(r"O[-\s]?(\d{1,5})", value.upper())
    if not match:
        return None
    return f"O-{int(match.group(1)):04d}"


def normalize_project_code(value: str) -> str | None:
    match = re.search(r"SH[-\s]?(\d{1,5})", value.upper())
    if not match:
        return None
    return f"SH-{int(match.group(1)):04d}"
