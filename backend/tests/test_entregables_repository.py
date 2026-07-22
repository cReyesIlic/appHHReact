import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.services.entregables_repository import CARGOS, EntregablesRepository


class EntregablesRepositoryTests(unittest.TestCase):
    def patch_settings(self, temp_dir: str):
        return patch.object(settings, "database_dir", str(Path(temp_dir) / "master.sqlite"))

    def create_database(self) -> None:
        cargo_columns = ",".join(f"{cargo} real default 0" for cargo in CARGOS)
        with closing(sqlite3.connect(settings.sqlite_path)) as conn, conn:
            conn.executescript(
                f"""
                create table proyectos (
                    id integer primary key, codigo text, descripcion text, clasificacion text,
                    factor real, categoria_reg_id integer, tipo_id integer, id_area integer,
                    estado text, {cargo_columns}
                );
                create table oferta (
                    codigo text primary key, titulo text, cliente_directo text, cliente_final text,
                    tipo_servicio text, estado text, cod_proy text, horas_lic text, monto text
                );
                create table categoria_reg (id integer primary key, nombre text);
                create table tipo (id integer primary key, nombre text);
                create table area (id integer primary key, id_area text, area text);
                create table proyectos_extracted (
                    id integer primary key, codigo text, descripcion text, clasificacion text,
                    cargo text, cargo_raw text, hh real, item text, source_file text,
                    source_sheet text, confidence real, extracted_at text
                );
                create table proyecto_tarifas (id integer primary key, codigo text, source_file text);
                create table proyecto_gastos_reembolsables (id integer primary key, codigo text, source_file text);
                create table proyecto_extraction_audit (
                    id integer primary key, codigo text, source_file text, proyecto_filas integer,
                    tarifas_filas integer, gastos_filas integer, processing_time real, extracted_at text
                );
                create table hh_estimate_rows (id integer primary key, codigo text);
                """
            )
            conn.execute("insert into categoria_reg values (1, 'Hidraulica')")
            conn.execute("insert into tipo values (1, 'Memoria de cálculo')")
            conn.execute("insert into area values (1, '1001', 'Estación de bombeo')")
            conn.executemany(
                "insert into oferta values (?,?,?,?,?,?,?,?,?)",
                [
                    ("O-1000", "ID Sistema de bombeo", "Cliente A", "Mina A", "ID", "PG", "100", "35", "10"),
                    ("O-2000", "IC Estudio hidráulico", "Cliente B", "Mina B", "IC", "PG", "200", "50", "20"),
                ],
            )
            conn.execute(
                "insert into proyectos (id,codigo,descripcion,clasificacion,factor,categoria_reg_id,tipo_id,id_area,estado,jp,ib) "
                "values (1,'O-1000','Memoria hidráulica','Documento',1,1,1,1001,'nuevo',10,20)"
            )
            conn.execute(
                "insert into proyectos (id,codigo,descripcion,clasificacion,factor,categoria_reg_id,tipo_id,id_area,estado,jp) "
                "values (2,'O-1000','Reuniones','Actividad',1,1,1,1001,'nuevo',5)"
            )
            conn.executemany(
                "insert into proyectos_extracted "
                "(id,codigo,descripcion,clasificacion,cargo,cargo_raw,hh,item,source_file,source_sheet,confidence,extracted_at) "
                "values (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "O-2000", "Informe técnico", "Documento", "JP", "JP", 10, "1", "nuevo.xlsx", "HH", 0.9, "2026-07-21"),
                    (2, "O-2000", "Informe técnico", "Documento", "IB", "IB", 40, "1", "nuevo.xlsx", "HH", 0.9, "2026-07-21"),
                    (3, "O-2000", "Revisión antigua", "Documento", "IB", "IB", 500, "1", "viejo.xlsx", "HH", 0.9, "2026-01-01"),
                ],
            )

    def test_aggregates_projects_and_compares_sum_with_master(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.patch_settings(temp_dir):
            self.create_database()
            repository = EntregablesRepository()

            result = repository.aggregate_licitadas(view="proyecto", limit=20)
            rows = {row["key"]: row for row in result["rows"]}

            self.assertEqual(set(rows), {"O-1000", "O-2000"})
            self.assertEqual(rows["O-1000"]["total_hours"], 35)
            self.assertEqual(rows["O-1000"]["match_master_pct"], 100)
            self.assertEqual(rows["O-1000"]["comparison_status"], "match")
            self.assertEqual(rows["O-2000"]["total_hours"], 50)
            self.assertEqual(rows["O-2000"]["source_types"], ["own_reader"])

    def test_deliverable_view_does_not_sum_old_workbook_revision(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.patch_settings(temp_dir):
            self.create_database()
            repository = EntregablesRepository()

            result = repository.aggregate_licitadas(view="entregable", codigo="O-2000", limit=20)

            self.assertEqual(result["available_rows"], 1)
            self.assertEqual(result["rows"][0]["total_hours"], 50)
            self.assertEqual(result["rows"][0]["source_file"], "nuevo.xlsx")


if __name__ == "__main__":
    unittest.main()
