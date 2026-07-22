from pydantic import BaseModel, Field

from app.services.search_filters import SearchFilters


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessage] = []
    selected_codes: list[str] = []
    deep_pdf_read: bool = True
    working_context: dict = {}
    filters: SearchFilters | None = None
    session_id: str | None = None
    create_session_if_missing: bool = True


class ChatSessionCreateRequest(BaseModel):
    title: str = "Nueva conversación"


class ChatSessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Source(BaseModel):
    kind: str
    title: str
    url: str | None = None
    entry_id: str | None = None
    codigo: str | None = None
    score: float | None = None


class ToolTrace(BaseModel):
    tool: str
    status: str
    detail: str


class ChatResponse(BaseModel):
    answer: str
    tables: list[dict] = []
    charts: list[dict] = []
    sources: list[Source] = []
    trace: list[ToolTrace] = []
    suggested_codes: list[str] = []
    working_context: dict = {}
    session_id: str | None = None


class MasterSearchRequest(BaseModel):
    query: str | None = None
    codigo: str | None = None
    cliente: str | None = None
    limit: int = 25
    filters: SearchFilters | None = None


class MemoryRequest(BaseModel):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)
    scope: str = "personal"
    tags: list[str] = []


class ProposalSupportRequest(BaseModel):
    query: str = Field(min_length=1)
    selected_codes: list[str] = []
    limit: int = 16


class ExportRequest(BaseModel):
    title: str = "Respuesta ProyectoHH"
    answer: str
    tables: list[dict] = []
    charts: list[dict] = []
    sources: list[Source] = []


class WikiBuildRequest(BaseModel):
    markdown: str


class WikiEntryRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = ""
    category: str = "general"
    tags: list[str] = []
    pinned: bool = False
    source: str | None = None
    propuestas_referenciadas: list[str] = []
    filtros_aplicables: dict = {}


class WikiValidateRequest(BaseModel):
    entry_id: str


class WikiAutoCreateRequest(BaseModel):
    topic: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    source_kind: str = "analysis"
    candidate_codes: list[str] = []
    pin_if_operational: bool = True
    approve: bool = False
    existing_entry_id: str | None = None


class WikiSearchRequest(BaseModel):
    query: str
    mode: str = "content"
    limit: int = 8


class WikiSection(BaseModel):
    id: str
    title: str
    level: int
    path: list[str]
    content: str
    keywords: list[str] = []


class IngestBatchRequest(BaseModel):
    limit: int = 10
