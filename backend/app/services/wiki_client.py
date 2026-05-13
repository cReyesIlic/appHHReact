import httpx

from app.core.config import settings


class WikiClient:
    async def search(self, question: str, keywords: list[str]) -> list[dict]:
        if not settings.wiki_endpoint:
            return []
        headers = {"api-key": settings.wiki_api_key} if settings.wiki_api_key else {}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(settings.wiki_endpoint, json={"question": question, "keywords": keywords}, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data.get("results", []) if isinstance(data, dict) else []

