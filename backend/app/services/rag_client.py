import httpx

from app.core.config import settings


class RagClient:
    async def search(self, question: str, keywords: list[str], codes: list[str]) -> list[dict]:
        if not settings.rag_endpoint:
            return []
        payload = {"question": question, "keywords": keywords, "codes": codes}
        headers = {"api-key": settings.rag_api_key} if settings.rag_api_key else {}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(settings.rag_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        if isinstance(data, dict):
            return data.get("results", [])
        return data if isinstance(data, list) else []

    async def parse_pdf_bytes(self, filename: str, content: bytes) -> str:
        if not settings.liteparse_function_url:
            return ""
        files = {"file": (filename, content, "application/pdf")}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(settings.liteparse_function_url, files=files)
            response.raise_for_status()
            data = response.json()
        return data.get("text", "")

