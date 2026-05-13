from datetime import datetime

import httpx


class EconomicIndicators:
    _cache: dict[str, float | None] = {}

    async def uf_for_date(self, date_text: str | None) -> float | None:
        if not date_text:
            return None
        try:
            date = datetime.fromisoformat(str(date_text)[:10])
        except ValueError:
            return None
        return await self._uf(f"{date.day:02d}-{date.month:02d}-{date.year}")

    async def current_uf(self) -> float | None:
        return await self._uf(None)

    async def _uf(self, date: str | None) -> float | None:
        cache_key = date or "current"
        if cache_key in self._cache:
            return self._cache[cache_key]
        url = "https://mindicador.cl/api/uf" + (f"/{date}" if date else "")
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            serie = data.get("serie") or []
            if not serie:
                self._cache[cache_key] = None
                return None
            value = float(serie[0]["valor"])
            self._cache[cache_key] = value
            return value
        except Exception:
            self._cache[cache_key] = None
            return None
