import logging
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger("shimin.config")
_warned_deployments: set[str] = set()


def _warn_fallback(name: str, fallback: str) -> str:
    if name not in _warned_deployments:
        _warned_deployments.add(name)
        _logger.warning(
            "[config] %s no configurado en env; usando fallback '%s'. "
            "Definir AZURE_OPENAI_%s_DEPLOYMENT en App Settings para evitar errores en runtime.",
            name, fallback, name.upper(),
        )
    return fallback


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_dir: str | None = Field(default=None, alias="DATABASE_DIR")
    master_path: str | None = Field(default=None, alias="MASTER_PATH")
    master_path_blob: str | None = Field(default=None, alias="MASTER_PATH_BLOB")
    secret_openaikey: str | None = Field(default=None, alias="SECRET_OPENAIKEY")
    azure_openai_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY", "OPENAI_API_KEY"),
    )
    azure_openai_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_ENDPOINT", "OPENAI_API_BASE", "OPENAI_BASE_URL"),
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_CHAT_DEPLOYMENT", "AZURE_OPENAI_MODEL_DEPLOYMENT", "OPENAI_MODEL"),
    )
    azure_openai_planner_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_PLANNER_DEPLOYMENT")
    azure_openai_index_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_INDEX_DEPLOYMENT")
    azure_openai_answer_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_ANSWER_DEPLOYMENT")
    azure_openai_embedding_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-12-01-preview", validation_alias=AliasChoices("AZURE_OPENAI_API_VERSION", "OPENAI_API_VERSION"))

    tenant_id: str | None = Field(default=None, alias="TENANT_ID")
    client_id: str | None = Field(default=None, alias="CLIENT_ID")
    client_secret: str | None = Field(default=None, alias="CLIENT_SECRET")
    site_name: str | None = Field(default=None, alias="SITE_NAME")
    site_url_ofertas: str | None = Field(default=None, alias="SITE_URL_OFERTAS")
    site_url_proyectos: str | None = Field(default=None, alias="SITE_URL_PROYECTOS")
    sharepoint_site: str | None = Field(default=None, alias="SHAREPOINT_SITE")

    azure_connection_string: str | None = Field(default=None, alias="AZURE_CONNECTION_STRING")
    container_name: str | None = Field(default=None, alias="CONTAINER_NAME")
    blob_name: str | None = Field(default=None, alias="BLOB_NAME")
    connection_to_pdf: str | None = Field(default=None, alias="CONNECTION_TO_PDF")

    # Microservicio Azure Function de extracción de presupuesto (HH + tarifas + reembolsables)
    budget_extractor_url: str | None = Field(default=None, alias="BUDGET_EXTRACTOR_URL")
    budget_extractor_api_key: str | None = Field(default=None, alias="BUDGET_EXTRACTOR_API_KEY")

    # Fuente de Excels de HH licitadas. Acepta:
    #   - path local relativo o absoluto (ej. "storage/emitted_offer_assets/excel")
    #   - "blob://<container>/<prefix>"  → se baja a cache temporal antes de leer
    # Por defecto usa el cache local; si en el futuro migran a blob, basta con cambiar el env var.
    hh_excel_source: str = Field(default="storage/emitted_offer_assets/excel", alias="HH_EXCEL_SOURCE")
    hh_excel_cache_dir: str = Field(default="storage/hh_excel_ingestion", alias="HH_EXCEL_CACHE_DIR")

    liteparse_function_url: str | None = Field(default=None, alias="LITEPARSE_FUNCTION_URL")
    rag_endpoint: str | None = Field(default=None, alias="RAG_ENDPOINT")
    rag_api_key: str | None = Field(default=None, alias="RAG_API_KEY")
    wiki_endpoint: str | None = Field(default=None, alias="WIKI_ENDPOINT")
    wiki_api_key: str | None = Field(default=None, alias="WIKI_API_KEY")

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
    ]
    export_dir: Path = Path("exports")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.project_root / path

    @property
    def sqlite_path(self) -> Path:
        base = Path(self.database_dir or "storage")
        if base.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            return self.resolve_path(base)
        return self.resolve_path(base / "master.sqlite")

    @property
    def openai_key(self) -> str | None:
        return self.azure_openai_key or self.secret_openaikey

    @property
    def planner_deployment(self) -> str:
        return self.azure_openai_planner_deployment or _warn_fallback("planner", "gpt-5.4-nano")

    @property
    def index_deployment(self) -> str:
        return self.azure_openai_index_deployment or self.azure_openai_deployment or _warn_fallback("index", "gpt-5.4-mini")

    @property
    def answer_deployment(self) -> str:
        return self.azure_openai_answer_deployment or self.azure_openai_deployment or _warn_fallback("answer", "gpt-5.4")

    @property
    def embedding_deployment(self) -> str:
        return self.azure_openai_embedding_deployment or _warn_fallback("embedding", "text-embedding-3-small")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
