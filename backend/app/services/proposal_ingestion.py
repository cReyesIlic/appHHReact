from app.services.knowledge_extractor import KnowledgeExtractor
from app.services.knowledge_models import ProposalKnowledge, ProposalMetadata
from app.services.master_repository import MasterRepository
from app.services.rag_store import RagStore
from app.services.sharepoint_client import SharePointClient


class ProposalIngestionService:
    def __init__(self) -> None:
        self.sharepoint = SharePointClient()
        self.master = MasterRepository()
        self.extractor = KnowledgeExtractor()
        self.store = RagStore()

    async def discover_offers(self, limit: int = 50) -> dict:
        folders = await self.sharepoint.list_offer_folders(limit=limit)
        return {"count": len(folders), "offers": folders}

    async def ingest_code(self, codigo: str) -> dict:
        codigo = codigo.upper().strip()
        pdfs = await self.sharepoint.list_pdfs(codigo)
        latest = self.sharepoint.select_latest_pdf(pdfs)
        if not latest:
            return {"codigo": codigo, "status": "no_pdf", "pdfs_found": len(pdfs)}

        content = await self.sharepoint.download_pdf(latest)
        local_path = self.sharepoint.save_pdf_locally(codigo, latest.get("name", "proposal.pdf"), content)
        first_pages = self.sharepoint.extract_first_pages_text(content, pages=5)
        full_text = self.sharepoint.extract_full_text(content)
        metadata = self._metadata(codigo, latest, str(local_path))
        knowledge = await self.extractor.extract(metadata, first_pages, full_text)
        chunks = self.store.make_chunks(
            codigo=codigo,
            text=full_text,
            source=latest.get("webUrl") or str(local_path),
            metadata={**metadata.model_dump(), **knowledge.model_dump()},
        )
        self.store.upsert_proposal(metadata, knowledge)
        self.store.replace_chunks(codigo, chunks)
        return {
            "codigo": codigo,
            "status": "indexed",
            "pdf": latest.get("name"),
            "chunks": len(chunks),
            "keywords": knowledge.keywords,
            "metadata": metadata.model_dump(),
        }

    async def ingest_batch(self, limit: int = 10) -> dict:
        offers = (await self.discover_offers(limit=limit))["offers"]
        results = []
        for offer in offers:
            results.append(await self.ingest_code(offer["codigo"]))
        return {"requested": limit, "processed": len(results), "results": results}

    def _metadata(self, codigo: str, pdf: dict, local_path: str) -> ProposalMetadata:
        master = self.master.search(codigo=codigo, limit=1)
        row = master[0] if master else {}
        return ProposalMetadata(
            codigo=codigo,
            pdf_name=pdf.get("name", ""),
            url=pdf.get("webUrl"),
            local_path=local_path,
            cliente=row.get("cliente_directo"),
            cliente_final=row.get("cliente_final"),
            titulo=row.get("titulo"),
            estado=row.get("estado"),
            tipo_servicio=row.get("tipo_servicio"),
            fecha_recepcion=row.get("fecha_recep") or row.get("fecha_recepcion"),
        )

