import json
import sqlite3
import unicodedata

from app.core.config import settings
from app.services.llm import LlmService
from app.services.sharepoint_client import SharePointClient


class ProposalIndexService:
    def __init__(self) -> None:
        self.llm = LlmService()
        self.sharepoint = SharePointClient()
        self._ensure_table()

    async def build_for_code(self, codigo: str) -> dict:
        pdfs = await self.sharepoint.list_pdfs(codigo)
        indexed = []
        for pdf in pdfs:
            content = await self.sharepoint.download_pdf(pdf)
            first_pages = self.sharepoint.extract_first_pages_text(content, pages=5)
            index = await self.llm.summarize_proposal_index(codigo, pdf.get("name", ""), first_pages)
            row = {
                "codigo": codigo.upper(),
                "pdf_name": pdf.get("name", ""),
                "url": pdf.get("webUrl"),
                "summary": index["summary"],
                "keywords": index["keywords"],
                "first_pages_text": first_pages[:20000],
            }
            self._upsert(row)
            indexed.append({"pdf_name": row["pdf_name"], "url": row["url"], "keywords": row["keywords"]})
        return {"codigo": codigo, "pdfs_found": len(pdfs), "indexed": indexed}

    def search(self, query: str, codes: list[str] | None = None, limit: int = 10) -> list[dict]:
        terms = [self._norm(term) for term in query.split() if len(term) >= 3]
        if not terms:
            return []

        sql = "select codigo, pdf_name, url, summary, keywords, first_pages_text from proposal_index"
        params: list[str] = []
        if codes:
            placeholders = ",".join("?" for _ in codes)
            sql += f" where codigo in ({placeholders})"
            params.extend(code.upper() for code in codes)

        with sqlite3.connect(settings.sqlite_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        ranked = []
        for codigo, pdf_name, url, summary, keywords, first_pages_text in rows:
            haystack = self._norm(" ".join([codigo, pdf_name, summary, keywords, first_pages_text]))
            score = sum(1 for term in terms if term in haystack)
            if score:
                ranked.append(
                    {
                        "codigo": codigo,
                        "title": pdf_name,
                        "url": url,
                        "summary": summary,
                        "keywords": json.loads(keywords or "[]"),
                        "score": float(score),
                    }
                )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]

    def _ensure_table(self) -> None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                create table if not exists proposal_index (
                    codigo text not null,
                    pdf_name text not null,
                    url text,
                    summary text,
                    keywords text,
                    first_pages_text text,
                    updated_at text default current_timestamp,
                    primary key (codigo, pdf_name)
                )
                """
            )

    def _upsert(self, row: dict) -> None:
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute(
                """
                insert into proposal_index (codigo, pdf_name, url, summary, keywords, first_pages_text, updated_at)
                values (?, ?, ?, ?, ?, ?, current_timestamp)
                on conflict(codigo, pdf_name) do update set
                    url = excluded.url,
                    summary = excluded.summary,
                    keywords = excluded.keywords,
                    first_pages_text = excluded.first_pages_text,
                    updated_at = current_timestamp
                """,
                (
                    row["codigo"],
                    row["pdf_name"],
                    row["url"],
                    row["summary"],
                    json.dumps(row["keywords"], ensure_ascii=False),
                    row["first_pages_text"],
                ),
            )

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
