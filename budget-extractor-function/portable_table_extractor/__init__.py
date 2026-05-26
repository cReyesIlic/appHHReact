"""
Portable Table Extractor - Motor de extracción de tablas desde Excel
Versión simplificada para integración en cualquier proyecto
"""

from .excel_table_extractor import ExcelTableExtractor
from .schemas import (
    TableType, 
    ExtractedTable, 
    ExcelProcessingResult,
    StandardRole
)
from .config import (
    ROLE_PATTERNS,
    SHEET_NAME_KEYWORDS,
    match_role_pattern,
    is_hierarchy_code
)

__version__ = "1.0.0"
__all__ = [
    "ExcelTableExtractor",
    "TableType",
    "ExtractedTable", 
    "ExcelProcessingResult",
    "StandardRole",
    "ROLE_PATTERNS",
    "SHEET_NAME_KEYWORDS",
    "match_role_pattern",
    "is_hierarchy_code"
]
