import json

from app.services.knowledge_models import ProposalKnowledge, ProposalMetadata
from app.services.llm import LlmService
from app.core.config import settings


class KnowledgeExtractor:
    def __init__(self) -> None:
        self.llm = LlmService()

    async def extract(self, metadata: ProposalMetadata, first_pages_text: str, full_text_sample: str) -> ProposalKnowledge:
        if not self.llm.client:
            return ProposalKnowledge(
                codigo=metadata.codigo,
                resumen_ejecutivo=first_pages_text[:1200],
                keywords=self.llm.extract_keywords(first_pages_text),
                criterios_busqueda=self.llm.extract_keywords(first_pages_text),
            )

        prompt = {
            "metadata": metadata.model_dump(),
            "first_pages_text": first_pages_text[:14000],
            "full_text_sample": full_text_sample[:8000],
        }
        try:
            content = await self.llm._chat(
                deployment=settings.index_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extrae conocimiento estructurado de una oferta tecnica/comercial. "
                            "Devuelve solo JSON valido con keys: resumen_ejecutivo, objetivo, alcance, entregables, "
                            "disciplinas, equipos_sistemas, clientes_industrias, keywords, criterios_busqueda, "
                            "util_para, riesgos_limitaciones. No inventes; si no aparece, deja lista vacia."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                max_completion_tokens=4096,
                response_format={"type": "json_object"},
            )
            data = json.loads(content)
        except Exception:
            data = {"resumen_ejecutivo": first_pages_text[:1200], "keywords": self.llm.extract_keywords(first_pages_text)}
        data = self._coerce(data)
        return ProposalKnowledge(codigo=metadata.codigo, **data)

    def _coerce(self, data: dict) -> dict:
        text_fields = ["resumen_ejecutivo", "objetivo"]
        list_fields = [
            "alcance",
            "entregables",
            "disciplinas",
            "equipos_sistemas",
            "clientes_industrias",
            "keywords",
            "criterios_busqueda",
            "util_para",
            "riesgos_limitaciones",
        ]
        for field in text_fields:
            value = data.get(field, "")
            if isinstance(value, list):
                data[field] = " ".join(str(item) for item in value)
            elif value is None:
                data[field] = ""
            else:
                data[field] = str(value)
        for field in list_fields:
            value = data.get(field, [])
            if value is None:
                data[field] = []
            elif isinstance(value, str):
                data[field] = [value]
            elif isinstance(value, list):
                data[field] = [str(item) for item in value if str(item).strip()]
            else:
                data[field] = [str(value)]
        return data
