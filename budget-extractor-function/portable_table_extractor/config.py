"""
Configuración estática - Patrones y reglas conocidas
Base de conocimiento para la lógica determinista
"""
import re
from typing import Dict, List

# =============================================================================
# PATRONES DE ROLES PROFESIONALES (EXPANDIDO)
# =============================================================================

ROLE_PATTERNS: Dict[str, List[str]] = {
    # Jefatura de Proyecto
    "JP": [
        r"\bjp\b", r"jefe.*proyecto", r"project.*manager", r"\bpm\b",
        r"lider.*proyecto", r"líder.*proyecto", r"lead.*project",
        r"gerente.*proyecto"  # En algunos casos GP se usa como JP
    ],
    "GP": [
        r"\bgp\b", r"gerente.*proyecto", r"project.*director",
        r"director.*proyecto", r"project.*manager", r"general.*manager"
    ],

    # Jefaturas Técnicas
    "JD": [
        r"\bjd\b", r"jefe.*disc", r"jefe.*especialidad", r"lead.*eng",
        r"discipline.*lead", r"líder.*disc", r"lider.*disc"
    ],
    "JI": [
        r"\bji\b", r"jefe.*ing", r"jefe.*ingeniería", r"engineering.*manager",
        r"líder.*ing", r"lider.*ing"
    ],

    # Coordinación
    "CN": [
        r"\bcn\b", r"coordinador.*nacional", r"coord.*nac", r"coordinator",
        r"consultor.*nac"
    ],
    "CI": [
        r"\bci\b", r"consultor.*internacional", r"coord.*int", r"international.*consultant",
        r"coordinador.*int"
    ],

    # Especialistas
    "ESP": [
        r"\besp\b", r"\bes\b", r"especialista", r"expert", r"specialist",
        r"senior.*specialist", r"esp\."
    ],

    # Ingenieros (Jerarquía A > B > C)
    "IA": [
        r"\bia\b", r"ing.*a\b", r"ingeniero.*a\b", r"ing\.?\s*a\b",
        r"ingeniero.*senior", r"senior.*eng", r"engineer.*a",
        r"inga\b", r"ing\.a\b"
    ],
    "IB": [
        r"\bib\b", r"ing.*b\b", r"ingeniero.*b\b", r"ing\.?\s*b\b",
        r"ingeniero.*semi", r"mid.*eng", r"engineer.*b",
        r"ingb\b", r"ing\.b\b"
    ],
    "IC": [
        r"\bic\b", r"ing.*c\b", r"ingeniero.*c\b", r"ing\.?\s*c\b",
        r"ingeniero.*junior", r"junior.*eng", r"engineer.*c",
        r"ingc\b", r"ing\.c\b"
    ],

    # Proyectistas (Jerarquía A > B)
    "PA": [
        r"\bpa\b", r"proy.*a\b", r"proyectista.*a\b", r"proy\.?\s*a\b",
        r"proyectista.*senior", r"senior.*designer", r"drafter.*a",
        r"proya\b", r"proy\.a\b"
    ],
    "PB": [
        r"\bpb\b", r"proy.*b\b", r"proyectista.*b\b", r"proy\.?\s*b\b",
        r"proyectista.*semi", r"mid.*designer", r"drafter.*b",
        r"proyb\b", r"proy\.b\b"
    ],
    "PC": [
        r"\bpc\b", r"proy.*c\b", r"proyectista.*c\b", r"proy\.?\s*c\b",
        r"proyectista.*junior", r"junior.*designer"
    ],

    # Dibujantes
    "DA": [r"\bda\b", r"dib.*a\b", r"dibujante.*senior", r"drafter.*senior", r"dib\.a"],
    "DB": [r"\bdb\b", r"dib.*b\b", r"dibujante.*junior", r"drafter.*junior", r"dib\.b"],

    # Control (NOTA: NO incluir \bdc\b ya que DC es tipo de documento)
    "CD": [
        r"\bcd\b", r"control.*doc", r"document.*control",
        r"ctrl.*doc", r"gestor.*doc", r"doc.*controller"
    ],
    "CP": [
        r"\bcp\b", r"control.*proy", r"project.*control", r"ctrl.*proy",
        r"planif", r"scheduler", r"planner"
    ],
    "QA": [
        r"\bqa\b", r"\bcc\b", r"control.*calidad", r"quality.*control",
        r"quality.*assurance", r"calidad", r"qa/qc"
    ],

    # Calculistas
    "CA": [r"\bca\b", r"calc.*a\b", r"calculista.*senior", r"structural.*eng.*a"],
    "CB": [r"\bcb\b", r"calc.*b\b", r"calculista.*junior", r"structural.*eng.*b"],

    # BIM
    "BIM": [
        r"\bbim\b", r"especialista.*bim", r"bim.*specialist", r"bim.*coordinator",
        r"coord.*bim", r"modelador.*bim"
    ],
    "ABIM": [
        r"\babim\b", r"bim.*senior", r"bim.*a\b", r"senior.*bim",
        r"especialista.*bim.*senior"
    ],
    "BBIM": [
        r"\bbbim\b", r"bim.*junior", r"bim.*b\b", r"junior.*bim",
        r"especialista.*bim.*junior"
    ],

    # Dirección
    "GP": [r"\bgp\b", r"gerente.*proy", r"project.*director", r"director.*proyecto"],
    "DI": [r"\bdi\b", r"director.*ing", r"engineering.*director", r"director.*ingeniería"],
    "SI": [r"\bsi\b", r"supervisor.*ing", r"engineering.*supervisor", r"supervisor.*ingeniería"]
}

# =============================================================================
# PALABRAS CLAVE POR TIPO DE TABLA
# =============================================================================

SHEET_NAME_KEYWORDS: Dict[str, List[str]] = {
    "entregables_profesionales": [
        "hh", "horas", "dotacion", "dotación", "man hours", "manpower",
        "entregables", "actividades", "recursos", "profesionales",
        "deliverables", "scope"
    ],
    "tarifas_profesionales": [
        "tarifa", "tarifas", "rate", "rates", "precio", "precios",
        "honorarios", "fee", "fees", "valorización", "valorizacion"
    ],
    "gastos_reembolsables": [
        "gasto", "gastos", "reembolso", "reembolsable", "reimbursable",
        "expense", "expenses", "viaje", "viajes", "travel",
        "viático", "viatico"
    ],
    "presupuesto_resumen": ["presupuesto", "budget", "resumen", "summary", "total", "costo", "cost"],
    "cronograma": ["cronograma", "schedule", "plazo", "plazos", "timeline", "fecha", "fechas", "entrega"]
}

# =============================================================================
# SINÓNIMOS DE TIPOS DE ÍTEM (DOCUMENTO/PLANO/ACTIVIDAD)
# =============================================================================

ITEM_TYPE_SYNONYMS = {
    "DOCUMENTO": [
        "dc", "doc", "documento", "document", "memoria", "informe",
        "report", "especificación", "especificacion", "spec",
        "procedimiento", "procedure", "manual", "estudio", "study"
    ],
    "PLANO": [
        "pl", "pla", "plano", "drawing", "dwg", "diagrama", "diagram",
        "layout", "esquema", "isométrico", "isometrico", "iso"
    ],
    "ACTIVIDAD": [
        "gl", "gi", "act", "actividad", "activity", "tarea", "task",
        "general", "gestión", "gestion", "coordinación", "coordinacion",
        "actualmente"  # Typo común
    ]
}

# =============================================================================
# PALABRAS CLAVE DE COLUMNAS (EXPANDIDO)
# =============================================================================

COLUMN_KEYWORDS = {
    "ITEM": [
        "item", "ítem", "codigo", "código", "code", "id", "n°", "nº", "num",
        "número", "numero", "#", "no.", "ref"
    ],
    "DESCRIPTION": [
        "descripción", "descripcion", "description", "desc", "actividad",
        "entregable", "deliverable", "activity", "tarea", "task", "nombre",
        "name", "título", "titulo", "title", "documento", "document"
    ],
    "DISCIPLINE": [
        "disciplina", "discipline", "disc", "especialidad", "specialty",
        "área", "area", "depto", "departamento", "department"
    ],
    "QUANTITY": [
        "cantidad", "qty", "quantity", "cant", "q", "unid", "unidad",
        "unit", "count", "nro"
    ],
    "PRICE": [
        "precio", "tarifa", "rate", "valor", "price", "monto", "amount",
        "costo", "cost", "honorario", "fee"
    ],
    "TOTAL": [
        "total", "sum", "suma", "subtotal", "grand total", "total general"
    ],
    "CURRENCY": [
        "moneda", "currency", "uf", "clp", "usd", "$", "pesos", "dólares",
        "dollars"
    ],
    "DOCUMENT": [
        "dc", "doc", "documento", "document", "docs", "documentos"
    ],
    "DRAWING": [
        "pl", "pla", "plano", "drawing", "dwg", "planos", "drawings"
    ],
    "ACTIVITY": [
        "gl", "gi", "act", "actividad", "activity", "general", "gestión"
    ],
    "TYPE": [
        "tipo", "type", "categoria", "categoría", "category", "clase", "class"
    ]
}

# =============================================================================
# PATRONES DE CÓDIGOS JERÁRQUICOS
# =============================================================================

HIERARCHY_PATTERNS = {
    "parent": re.compile(r"^\d+\.0$"),  # 1.0, 2.0, 3.0
    "child_level1": re.compile(r"^\d+\.\d+$"),  # 1.1, 1.2, 2.1
    "child_level2": re.compile(r"^\d+\.\d+\.\d+$"),  # 1.1.1, 2.3.4
    "child_level3": re.compile(r"^\d+\.\d+\.\d+\.\d+$")  # 1.1.1.1
}

SKIP_ROW_KEYWORDS = ["subtotal", "sub-total", "total general", "total final", "suma", "resumen", "notes", "notas", "n/a"]

THRESHOLDS = {
    "min_confidence_heuristic": 0.7,
    "min_confidence_ai": 0.5,
    "min_rows_for_valid_table": 3,
    "max_empty_rows_before_stop": 5,
    "min_role_columns": 2,
}

# =============================================================================
# HELPERS
# =============================================================================

def is_document_type_column(text: str) -> str:
    """
    Detecta si una columna es de tipo de documento (DC/PL/GL)
    DEBE ejecutarse ANTES de match_role_pattern para evitar confusiones

    Retorna: "DC", "PL", "GL" o None si no es tipo documento
    """
    if not text:
        return None

    text_upper = text.strip().upper()

    # Tipos de documento (exactos primero)
    if text_upper in ["DC", "DOC", "DOCUMENTO", "DOCUMENT"]:
        return "DC"

    # Tipos de plano
    if text_upper in ["PL", "PLA", "PLANO", "PLANOS", "DWG", "DRAWING", "DRAWINGS"]:
        return "PL"

    # Tipos de actividad/general
    if text_upper in ["GL", "GI", "ACT", "ACTIVIDAD", "ACTIVITY", "GENERAL"]:
        return "GL"

    return None


def match_role_pattern(text: str) -> str:
    """
    Matchea un texto contra patrones de roles
    IMPORTANTE: Ejecutar is_document_type_column() ANTES para evitar confusiones
    """
    if not text or len(text) > 50:
        return "UNKNOWN"

    text_lower = text.lower().strip()
    for role_code, patterns in ROLE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return role_code
    return "UNKNOWN"


def match_column_type(text: str) -> str:
    """Identifica el tipo de columna basado en su nombre"""
    if not text:
        return "UNKNOWN"
    
    text_lower = text.lower().strip()
    for col_type, keywords in COLUMN_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                return col_type
    return "UNKNOWN"


def is_hierarchy_code(text: str) -> bool:
    """Verifica si un texto parece un código jerárquico"""
    if not text:
        return False
    text = str(text).strip()
    return any(pattern.match(text) for pattern in HIERARCHY_PATTERNS.values())


def get_hierarchy_level(text: str) -> int:
    """Retorna el nivel de jerarquía de un código"""
    if not text:
        return -1
    
    text = str(text).strip()
    if HIERARCHY_PATTERNS["parent"].match(text):
        return 0
    elif HIERARCHY_PATTERNS["child_level1"].match(text):
        return 1
    elif HIERARCHY_PATTERNS["child_level2"].match(text):
        return 2
    elif HIERARCHY_PATTERNS["child_level3"].match(text):
        return 3
    return -1


def should_skip_row(text: str) -> bool:
    """Verifica si una fila debe ser ignorada"""
    if not text:
        return True
    text_lower = text.lower().strip()
    return any(keyword in text_lower for keyword in SKIP_ROW_KEYWORDS)


def normalize_number(value: any) -> float:
    """
    Normaliza un valor a número float, manejando casos edge:
    - "1", "1,0", "1.0" → 1.0
    - "-", "N/A", vacío → 0.0
    - "HH", "hrs" → 0.0 (text invalido)
    - "1.234,56" (formato europeo) → 1234.56
    - "1,234.56" (formato US) → 1234.56
    """
    if value is None or value == "":
        return 0.0

    # Si ya es número
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else 0.0

    # Convertir a string y limpiar
    text = str(value).strip().upper()

    # Casos especiales
    if text in ["-", "N/A", "NA", "TBD", "HH", "HRS", "HOURS", ""]:
        return 0.0

    # Remover texto común
    text = text.replace("HH", "").replace("HRS", "").replace("HOURS", "").strip()

    # Intentar conversión directa
    try:
        return float(text)
    except:
        pass

    # Manejar formato con comas y puntos
    # Detectar formato: si último separador es coma, es formato europeo
    has_comma = "," in text
    has_dot = "." in text

    if has_comma and has_dot:
        # Determinar cuál es decimal
        last_comma_pos = text.rfind(",")
        last_dot_pos = text.rfind(".")

        if last_comma_pos > last_dot_pos:
            # Formato europeo: 1.234,56
            text = text.replace(".", "").replace(",", ".")
        else:
            # Formato US: 1,234.56
            text = text.replace(",", "")
    elif has_comma:
        # Solo coma: podría ser decimal o miles
        if text.count(",") == 1 and len(text.split(",")[1]) <= 2:
            # Probablemente decimal: 1,5
            text = text.replace(",", ".")
        else:
            # Probablemente miles: 1,234
            text = text.replace(",", "")

    # Intentar conversión final
    try:
        result = float(text)
        return result if result >= 0 else 0.0
    except:
        return 0.0


def normalize_column_name(text: str) -> str:
    """
    Normaliza nombre de columna:
    - Quita espacios extra, saltos de línea
    - Quita acentos opcionales
    - Convierte a minúsculas
    """
    if not text:
        return ""

    # Convertir a string y limpiar
    text = str(text).strip()

    # Reemplazar saltos de línea y tabs por espacio
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")

    # Múltiples espacios a uno solo
    text = " ".join(text.split())

    return text


def infer_item_type_from_description(description: str) -> str:
    """
    Infiere tipo de ítem desde la descripción cuando no está explícito
    Retorna: DOCUMENTO, PLANO, ACTIVIDAD o DESCONOCIDO
    """
    if not description:
        return "DESCONOCIDO"

    desc_lower = description.lower().strip()

    # Buscar keywords de plano (más específico primero)
    for keyword in ITEM_TYPE_SYNONYMS["PLANO"]:
        if keyword in desc_lower:
            return "PLANO"

    # Buscar keywords de documento
    for keyword in ITEM_TYPE_SYNONYMS["DOCUMENTO"]:
        if keyword in desc_lower:
            return "DOCUMENTO"

    # Buscar keywords de actividad
    for keyword in ITEM_TYPE_SYNONYMS["ACTIVIDAD"]:
        if keyword in desc_lower:
            return "ACTIVIDAD"

    return "DESCONOCIDO"


def match_item_type(text: str) -> str:
    """
    Matchea texto contra sinónimos de tipos de ítem
    Retorna: DOCUMENTO, PLANO, ACTIVIDAD o DESCONOCIDO
    """
    if not text:
        return "DESCONOCIDO"

    text_lower = text.lower().strip()

    for item_type, synonyms in ITEM_TYPE_SYNONYMS.items():
        if any(syn in text_lower for syn in synonyms):
            return item_type

    return "DESCONOCIDO"
