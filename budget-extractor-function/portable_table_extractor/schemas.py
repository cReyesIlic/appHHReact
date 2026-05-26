"""
Schemas - Contrato de datos robusto con Pydantic
Garantiza que lo que salga del módulo sea estrictamente válido
"""
from enum import Enum
from typing import List, Optional, Dict, Union, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class TableType(str, Enum):
    """Tipos de tablas detectables en Excel"""
    ENTREGABLES = "entregables_profesionales"
    TARIFAS = "tarifas_profesionales"
    GASTOS = "gastos_reembolsables"
    PRESUPUESTO = "presupuesto_resumen"
    CRONOGRAMA = "cronograma"
    UNKNOWN = "desconocido"


class StandardRole(str, Enum):
    """Roles profesionales estándar"""
    JP = "JP"  # Jefe de Proyecto
    JD = "JD"  # Jefe de Disciplina
    CN = "CN"  # Coordinador
    ESP = "ESP"  # Especialista
    IA = "IA"  # Ingeniero A
    IB = "IB"  # Ingeniero B
    IC = "IC"  # Ingeniero C
    PA = "PA"  # Proyectista A
    PB = "PB"  # Proyectista B
    PC = "PC"  # Proyectista C
    DA = "DA"  # Dibujante A
    DB = "DB"  # Dibujante B
    CD = "CD"  # Control de Documentos
    CP = "CP"  # Control de Proyectos
    CA = "CA"  # Calculista A
    CB = "CB"  # Calculista B
    GP = "GP"  # Gerente de Proyecto
    DI = "DI"  # Director de Ingeniería
    SI = "SI"  # Supervisor de Ingeniería
    UNKNOWN = "UNKNOWN"


# Modelo de tabla extraída simplificado
class ExtractedTable(BaseModel):
    """Resultado de extracción de una hoja Excel"""
    sheet_name: str = Field(..., description="Nombre de la hoja")
    table_type: TableType = Field(..., description="Tipo de tabla detectado")
    confidence: float = Field(..., description="Nivel de confianza (0.0-1.0)", ge=0.0, le=1.0)
    
    # Datos extraídos como diccionarios genéricos
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Filas extraídas como diccionarios"
    )
    
    # Metadata adicional
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Información adicional de procesamiento"
    )
    
    # Estadísticas
    num_rows: int = Field(0, description="Número de filas extraídas", ge=0)
    header_row_index: Optional[int] = Field(None, description="Índice de fila de encabezado")
    detection_method: str = Field("", description="Método usado (heuristic, ai, hybrid)")
    processing_time_seconds: Optional[float] = Field(None, description="Tiempo de procesamiento")
    
    @model_validator(mode='after')
    def set_num_rows(self):
        """Auto-calcula número de filas desde data"""
        if self.data:
            self.num_rows = len(self.data)
        return self


class ExcelProcessingResult(BaseModel):
    """Resultado completo del procesamiento de un archivo Excel"""
    file_path: str = Field(..., description="Ruta del archivo procesado")
    file_name: str = Field(..., description="Nombre del archivo")
    
    tables: List[ExtractedTable] = Field(
        default_factory=list,
        description="Tablas extraídas"
    )
    
    # Estadísticas generales
    total_sheets: int = Field(0, description="Total de hojas en el Excel", ge=0)
    sheets_processed: int = Field(0, description="Hojas procesadas exitosamente", ge=0)
    sheets_skipped: int = Field(0, description="Hojas omitidas", ge=0)
    
    # Contadores por tipo
    tables_entregables: int = Field(0, ge=0)
    tables_tarifas: int = Field(0, ge=0)
    tables_gastos: int = Field(0, ge=0)
    tables_other: int = Field(0, ge=0)
    
    # Errores
    errors: List[str] = Field(default_factory=list, description="Errores encontrados")
    
    # Metadata
    processing_time_seconds: Optional[float] = None
    processed_at: Optional[str] = None
    
    def get_table_by_type(self, table_type: TableType) -> List[ExtractedTable]:
        """Filtra tablas por tipo"""
        return [t for t in self.tables if t.table_type == table_type]
    
    def get_summary(self) -> Dict[str, Any]:
        """Resumen ejecutivo"""
        return {
            "file": self.file_name,
            "sheets_total": self.total_sheets,
            "tables_extracted": len(self.tables),
            "by_type": {
                "entregables": self.tables_entregables,
                "tarifas": self.tables_tarifas,
                "gastos": self.tables_gastos,
                "other": self.tables_other
            },
            "errors": len(self.errors)
        }
