"""Crea índices funcionales sobre metadata JSON para acelerar SearchFilters.

Idempotente: usa `create index if not exists`. Seguro de re-ejecutar.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402


INDEXES = [
    # rag_child_chunks metadata
    ("idx_child_meta_estado", "rag_child_chunks", "json_extract(metadata, '$.estado')"),
    ("idx_child_meta_categoria", "rag_child_chunks", "json_extract(metadata, '$.estado_categoria')"),
    ("idx_child_meta_cliente", "rag_child_chunks", "lower(json_extract(metadata, '$.cliente'))"),
    ("idx_child_meta_cliente_final", "rag_child_chunks", "lower(json_extract(metadata, '$.cliente_final'))"),
    ("idx_child_meta_tipo", "rag_child_chunks", "json_extract(metadata, '$.tipo_servicio')"),
    # rag_parent_sections metadata
    ("idx_parent_meta_estado", "rag_parent_sections", "json_extract(metadata, '$.estado')"),
    ("idx_parent_meta_categoria", "rag_parent_sections", "json_extract(metadata, '$.estado_categoria')"),
    ("idx_parent_meta_cliente", "rag_parent_sections", "lower(json_extract(metadata, '$.cliente'))"),
    ("idx_parent_meta_cliente_final", "rag_parent_sections", "lower(json_extract(metadata, '$.cliente_final'))"),
    ("idx_parent_meta_tipo", "rag_parent_sections", "json_extract(metadata, '$.tipo_servicio')"),
    # codigo lookups (probablemente ya existe pero por si acaso)
    ("idx_child_codigo", "rag_child_chunks", "codigo"),
    ("idx_parent_codigo", "rag_parent_sections", "codigo"),
]


def main() -> None:
    db = settings.sqlite_path
    print(f"Aplicando índices en: {db}")
    with sqlite3.connect(db) as conn:
        for name, table, expr in INDEXES:
            sql = f"create index if not exists {name} on {table}({expr})"
            print(f"  · {name}")
            conn.execute(sql)
        conn.commit()
    print("Listo.")


if __name__ == "__main__":
    main()
