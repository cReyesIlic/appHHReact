import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

from app.core.config import settings
from app.services.blob_storage import BlobStorageService
from app.services.proposal_taxonomy import status_category
from app.services.search_filters import SearchFilters


EXPECTED_COLUMNS = {
    "codigo": ["codigo", "cod prop", "codigo prop", "cod_propuesta"],
    "fecha_recep": ["fecha recep", "fecha recepcion"],
    "cliente_directo": ["cliente directo", "cliente"],
    "cliente_final": ["cliente final"],
    "titulo": ["titulo", "nombre oferta", "propuesta"],
    "estado": ["estado"],
    "tipo_servicio": ["tipo servicio", "servicio"],
    "cod_proy": ["cod proy", "codigo proyecto", "proyecto"],
    "monto": ["monto", "valor"],
    "horas_lic": ["horas lic", "hh", "horas"],
    "tarifa_prom": ["tarifa prom", "tarifa"],
}

TERM_WEIGHTS = {
    "dewatering": 8.0,
    "desague": 7.0,
    "desaguar": 7.0,
    "drenaje": 5.0,
    "abatimiento": 5.0,
    "rajo": 5.0,
    "pit": 4.0,
    "bombeo": 4.0,
    "bomba": 4.0,
    "bombas": 4.0,
    "impulsion": 3.0,
    "relaves": 8.0,
    "relave": 8.0,
    "tailings": 8.0,
    "tranque": 6.0,
    "relaveducto": 8.0,
    "rejeitoduto": 8.0,
    "rejeito": 6.0,
    "disposicion": 6.0,
    "depositacion": 6.0,
    "deposito": 4.0,
    "factibilidad": 5.0,
    "prefactibilidad": 5.0,
    "alternativa": 4.0,
    "agua": 2.0,
    "aguas": 2.0,
    "mina": 2.0,
}


class MasterRepository:
    def __init__(self) -> None:
        self.blob = BlobStorageService()

    def search(
        self,
        query: str | None = None,
        codigo: str | None = None,
        cliente: str | None = None,
        limit: int = 25,
        filters: SearchFilters | None = None,
    ) -> list[dict]:
        df = self._load()
        if df.empty:
            return []

        # Construir un SearchFilters efectivo desde los argumentos legacy si no vino uno explícito
        eff = filters or SearchFilters()
        if codigo and not eff.codigos:
            eff = eff.model_copy(update={"codigos": [codigo.upper()]})
        if cliente and not eff.clientes:
            eff = eff.model_copy(update={"clientes": [cliente]})
        if query and not eff.query:
            eff = eff.model_copy(update={"query": query})

        mask = self._filter_mask(df, eff)
        if eff.query:
            terms = [self._norm(t) for t in eff.query.split() if len(t) >= 3]
            text = df.fillna("").astype(str).agg(" ".join, axis=1).map(self._norm)
            if terms:
                scores = pd.Series([0] * len(df))
                for term in terms:
                    scores += text.str.contains(term, na=False).astype(int)
                mask &= scores > 0
                df = df.assign(_score=scores)
                return (
                    df[mask]
                    .sort_values("_score", ascending=False)
                    .drop(columns=["_score"])
                    .head(limit)
                    .fillna("")
                    .to_dict(orient="records")
                )

        return df[mask].head(limit).fillna("").to_dict(orient="records")

    def search_filtered(self, filters: SearchFilters, limit: int | None = None) -> list[dict]:
        return self.search(query=filters.query, limit=limit or filters.limit, filters=filters)

    def _filter_mask(self, df: pd.DataFrame, filters: SearchFilters) -> pd.Series:
        mask = pd.Series([True] * len(df), index=df.index)
        if filters.codigos and "codigo" in df.columns:
            codes_upper = [c.upper() for c in filters.codigos]
            # Match flexible: exact en codigo, contiene en codigo, exact/contiene en cod_proy.
            # Permite "O-2200", "SH-428", "SH-0428", "428" → cualquier columna que contenga el patrón.
            cod_norm = df["codigo"].astype(str).str.upper()
            proy_norm = df["cod_proy"].astype(str).str.upper() if "cod_proy" in df.columns else None
            row_mask = pd.Series([False] * len(df), index=df.index)
            for raw in codes_upper:
                # Variantes: literal, sin guion, sin ceros a la izquierda, con padding 4 dígitos
                variants = {raw}
                clean = raw.replace("-", "")
                variants.add(clean)
                # Detectar prefijo letra(s) + numero
                import re as _re
                m = _re.match(r"^([A-Z]+)?-?(\d+)$", raw)
                if m:
                    prefix = m.group(1) or ""
                    number = m.group(2)
                    number_int = int(number)
                    variants.add(f"{prefix}-{number}" if prefix else number)
                    variants.add(f"{prefix}-{number_int:04d}" if prefix else f"{number_int:04d}")
                    variants.add(f"{prefix}{number}" if prefix else number)
                    # cod_proy a veces viene como "428.0" o "428" (sin prefijo)
                    variants.add(str(number_int))
                    variants.add(f"{number_int}.0")
                    variants.add(f"{number_int:04d}.0")
                # Match: substring en codigo OR cod_proy
                for v in variants:
                    row_mask |= cod_norm.str.contains(v, regex=False, na=False)
                    if proy_norm is not None:
                        row_mask |= proy_norm.str.contains(v, regex=False, na=False)
            mask &= row_mask
        if filters.clientes:
            normalized = [self._norm(c) for c in filters.clientes]
            client_cols = [col for col in ["cliente_directo", "cliente_final"] if col in df.columns]
            client_mask = pd.Series([False] * len(df), index=df.index)
            for col in client_cols:
                col_norm = df[col].astype(str).map(self._norm)
                for token in normalized:
                    client_mask |= col_norm.str.contains(token, na=False)
            mask &= client_mask
        if filters.estados and "estado" in df.columns:
            est_upper = [e.upper() for e in filters.estados]
            mask &= df["estado"].astype(str).str.upper().isin(est_upper)
        if filters.estado_categoria and "estado" in df.columns:
            cats = set(filters.estado_categoria)
            mask &= df["estado"].astype(str).map(lambda v: status_category(v) in cats)
        if filters.tipos_servicio and "tipo_servicio" in df.columns:
            tipos_upper = [t.upper() for t in filters.tipos_servicio]
            mask &= df["tipo_servicio"].astype(str).str.upper().apply(
                lambda value: any(t in value for t in tipos_upper)
            )
        if filters.monto_min is not None and "monto" in df.columns:
            mask &= pd.to_numeric(df["monto"], errors="coerce").fillna(-1) >= filters.monto_min
        if filters.monto_max is not None and "monto" in df.columns:
            mask &= pd.to_numeric(df["monto"], errors="coerce").fillna(-1) <= filters.monto_max
        if filters.fecha_desde and "fecha_recep" in df.columns:
            fechas = pd.to_datetime(df["fecha_recep"], errors="coerce")
            mask &= fechas >= pd.Timestamp(filters.fecha_desde)
        if filters.fecha_hasta and "fecha_recep" in df.columns:
            fechas = pd.to_datetime(df["fecha_recep"], errors="coerce")
            mask &= fechas <= pd.Timestamp(filters.fecha_hasta)
        return mask

    def search_many(self, queries: list[str], limit: int = 25) -> list[dict]:
        df = self._load()
        if df.empty:
            return []
        text = df.fillna("").astype(str).agg(" ".join, axis=1).map(self._norm)
        scores = pd.Series([0.0] * len(df))

        for query in queries:
            normalized_query = self._norm(query)
            terms = [term for term in normalized_query.split() if len(term) >= 3]
            if not terms:
                continue
            phrase = " ".join(terms)
            if len(terms) > 1:
                scores += text.str.contains(phrase, na=False, regex=False).astype(float) * (len(terms) + 2)
            for term in terms:
                scores += text.str.contains(term, na=False, regex=False).astype(float) * TERM_WEIGHTS.get(term, 1.0)

        compound_boosts = {
            "dewatering mina": 14.0,
            "agua mina": 10.0,
            "aguas fondo mina": 10.0,
            "fondo mina": 8.0,
            "rajo abierto": 10.0,
            "sistema de bombeo": 8.0,
            "sistema dewatering": 12.0,
            "disposicion alternativa relaves": 18.0,
            "factibilidad disposicion relaves": 18.0,
            "transporte de relaves": 14.0,
            "relaves y aguas recuperadas": 16.0,
            "deposito de relaves": 14.0,
            "tranque relaves": 12.0,
            "sistema de drenaje proyecto tranque": 10.0,
        }
        for phrase, weight in compound_boosts.items():
            scores += text.str.contains(phrase, na=False, regex=False).astype(float) * weight

        mask = scores > 0
        if not mask.any():
            return []
        return (
            df.assign(_score=scores)[mask]
            .sort_values("_score", ascending=False)
            .drop(columns=["_score"])
            .head(limit)
            .fillna("")
            .to_dict(orient="records")
        )

    def count_offers(self) -> int:
        df = self._load()
        if df.empty:
            return 0
        if "codigo" not in df.columns:
            return len(df)
        return int(df["codigo"].astype(str).str.strip().ne("").sum())

    def all_offers(self) -> list[dict]:
        df = self._load()
        if df.empty:
            return []
        return df.fillna("").to_dict(orient="records")

    def refresh_from_excel(self) -> int:
        path = self._ensure_master_excel()
        if not path.exists():
            return 0
        df = self._read_excel(path)
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(settings.sqlite_path) as conn:
            df.to_sql("oferta", conn, if_exists="replace", index=False)
        return len(df)

    def _load(self) -> pd.DataFrame:
        self._ensure_sqlite()
        if settings.sqlite_path.exists():
            with sqlite3.connect(settings.sqlite_path) as conn:
                return pd.read_sql_query("select * from oferta", conn)
        excel_path = self._ensure_master_excel()
        if excel_path.exists():
            self.refresh_from_excel()
            return self._load()
        return pd.DataFrame()

    def _ensure_sqlite(self) -> None:
        if settings.sqlite_path.exists():
            return
        if (settings.connection_to_pdf or "").strip().upper() == "BLOB":
            self.blob.download(settings.blob_name, settings.sqlite_path)

    def _ensure_master_excel(self) -> Path:
        path = settings.resolve_path(settings.master_path or "storage/master.xlsx")
        if path.exists():
            return path
        self.blob.download(settings.master_path_blob, path)
        return path

    def _read_excel(self, path: Path) -> pd.DataFrame:
        raw = pd.read_excel(path, sheet_name="Ofertas", header=21)
        rename: dict[str, str] = {}
        normalized_cols = {self._norm(col): col for col in raw.columns}
        for target, variants in EXPECTED_COLUMNS.items():
            found = None
            for variant in variants:
                variant_norm = self._norm(variant)
                found = normalized_cols.get(variant_norm)
                if found:
                    break
                found = next((original for norm, original in normalized_cols.items() if variant_norm in norm), None)
                if found:
                    break
            if found:
                rename[found] = target
        df = raw.rename(columns=rename)
        keep = [col for col in EXPECTED_COLUMNS if col in df.columns]
        return df[keep].astype(str).replace({"nan": "No data", "None": "No data"})

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
