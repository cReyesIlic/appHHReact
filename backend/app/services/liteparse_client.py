from pathlib import Path

import httpx


class LiteParseClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8787") -> None:
        self.base_url = base_url.rstrip("/")

    async def health(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()

    async def parse_file(self, path: str | Path) -> dict:
        file_path = Path(path)
        with file_path.open("rb") as file:
            files = {"file": (file_path.name, file, "application/pdf")}
            async with httpx.AsyncClient(timeout=240) as client:
                response = await client.post(f"{self.base_url}/parse", files=files)
                response.raise_for_status()
                return response.json()

