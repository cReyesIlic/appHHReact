from pydantic import BaseModel, Field


class ProposalMetadata(BaseModel):
    codigo: str
    pdf_name: str
    url: str | None = None
    local_path: str | None = None
    cliente: str | None = None
    cliente_final: str | None = None
    titulo: str | None = None
    estado: str | None = None
    tipo_servicio: str | None = None
    fecha_recepcion: str | None = None


class ProposalKnowledge(BaseModel):
    codigo: str
    resumen_ejecutivo: str = ""
    objetivo: str = ""
    alcance: list[str] = Field(default_factory=list)
    entregables: list[str] = Field(default_factory=list)
    disciplinas: list[str] = Field(default_factory=list)
    equipos_sistemas: list[str] = Field(default_factory=list)
    clientes_industrias: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    criterios_busqueda: list[str] = Field(default_factory=list)
    util_para: list[str] = Field(default_factory=list)
    riesgos_limitaciones: list[str] = Field(default_factory=list)


class RagChunk(BaseModel):
    codigo: str
    chunk_id: str
    text: str
    source: str
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict = Field(default_factory=dict)

