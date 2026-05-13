import hashlib
import math
import re
import unicodedata

import numpy as np
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.config import settings
from app.services.credits import CreditService


class EmbeddingService:
    def __init__(self) -> None:
        self.deployment = settings.azure_openai_embedding_deployment or "local-hash-fallback"
        self.using_fallback = not bool(settings.azure_openai_embedding_deployment)
        self.azure = bool(settings.azure_openai_endpoint and settings.openai_key and not self.using_fallback)
        if self.azure:
            self.client = AsyncAzureOpenAI(
                api_key=settings.openai_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
        else:
            self.client = AsyncOpenAI(api_key=settings.openai_key) if settings.openai_key and not self.using_fallback else None

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean = [self._clean_text(text) for text in texts]
        if not clean:
            return []
        if not self.client:
            return [self._hash_embedding(text).tolist() for text in clean]
        response = await self.client.embeddings.create(model=self.deployment, input=clean)
        usage = getattr(response, "usage", None)
        if usage:
            try:
                CreditService().record_llm_usage(
                    model=self.deployment,
                    usage=usage,
                    action="embedding",
                    metadata={"items": len(clean)},
                )
            except Exception:
                pass
        return [item.embedding for item in response.data]

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query]))[0]

    def vector_to_blob(self, vector: list[float]) -> bytes:
        arr = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm:
            arr = arr / norm
        return arr.astype(np.float32).tobytes()

    def blob_to_vector(self, blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    def content_hash(self, text: str) -> str:
        return hashlib.sha1(self._clean_text(text).encode("utf-8")).hexdigest()

    def _clean_text(self, text: str) -> str:
        return " ".join(str(text or "").split())[:8000]

    def _hash_embedding(self, text: str, dim: int = 384) -> np.ndarray:
        # Development fallback only. Real deployments should set AZURE_OPENAI_EMBEDDING_DEPLOYMENT.
        vec = np.zeros(dim, dtype=np.float32)
        tokens = re.findall(r"[a-z0-9]{3,}", self._norm(text))
        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(float(np.dot(vec, vec)))
        return vec / norm if norm else vec

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or "").lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
