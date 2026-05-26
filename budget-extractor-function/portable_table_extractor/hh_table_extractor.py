"""
HHTableExtractor - Extractor específico para tablas de Horas-Hombre (HH)
Enfoque: Determinístico primero, IA solo para limpiar/normalizar

FLUJO:
1. Detectar headers (single o multi-línea) analizando filas
2. Clasificar columnas por tipo de dato (texto vs número)
3. Extraer datos determinísticamente
4. Usar IA SOLO para limpiar/normalizar roles no reconocidos
"""
import pandas as pd
import numpy as np
import re
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field


@dataclass
class ColumnInfo:
    """Información de una columna detectada"""
    idx: int
    name: str
    col_type: str  # 'item', 'description', 'quantity', 'role', 'total', 'unknown'
    role_code: Optional[str] = None  # Si es tipo 'role', el código normalizado
    disciplina: Optional[str] = None  # Si el header menciona disciplina
    data_type: str = 'unknown'  # 'numeric', 'text', 'mixed'
    sample_values: List[Any] = field(default_factory=list)


@dataclass 
class HeaderInfo:
    """Información del encabezado detectado"""
    start_row: int
    end_row: int  # Mismo que start si es single-line
    is_multi_row: bool
    columns: List[ColumnInfo] = field(default_factory=list)
    data_start_row: int = 0


@dataclass
class ExtractedRow:
    """Fila extraída"""
    item: Optional[str]
    description: str
    cantidad: Optional[float]
    man_hours: Dict[str, float]
    total_hh: float
    is_parent: bool = False  # Si es título de sección (1.0, 2.0)
    level: int = 0  # Nivel de jerarquía


class HHTableExtractor:
    """
    Extractor de tablas HH con enfoque determinístico.
    """
    
    # Palabras clave para detectar headers
    HEADER_KEYWORDS = [
        'item', 'ítem', 'codigo', 'código', 'id', 'n°', 'nº',
        'descripcion', 'descripción', 'actividad', 'documento', 
        'entregable', 'plano', 'deliverable', 'activity'
    ]
    
    # Patrones de roles profesionales
    ROLE_PATTERNS = {
        'JP': [r'\bjp\b', r'jefe.*proy', r'project.*manager', r'\bpm\b'],
        'JD': [r'\bjd\b', r'jefe.*disc', r'jefe.*ing', r'lead.*eng', r'discipline.*lead'],
        'ESP': [r'\besp\b', r'especialista', r'specialist'],
        'IA': [r'\bia\b', r'ing.*a\b', r'ingeniero.*senior', r'senior.*eng'],
        'IB': [r'\bib\b', r'ing.*b\b', r'ingeniero.*semi'],
        'IC': [r'\bic\b', r'ing.*c\b', r'ingeniero.*junior'],
        'PA': [r'\bpa\b', r'proy.*a\b', r'proyectista.*senior', r'proyectista.*a\b'],
        'PB': [r'\bpb\b', r'proy.*b\b', r'proyectista.*semi', r'proyectista.*b\b'],
        'PC': [r'\bpc\b', r'proy.*c\b', r'proyectista.*junior'],
        'CD': [r'\bcd\b', r'control.*doc', r'document.*control'],  # NO incluir \bdc\b aquí
        'CP': [r'\bcp\b', r'control.*proy', r'project.*control'],
        'CN': [r'\bcn\b', r'coordinador', r'coordinator'],
        'CA': [r'\bca\b', r'calculista.*a'],
        'CB': [r'\bcb\b', r'calculista.*b'],
        'ABIM': [r'\babim\b', r'bim'],
    }
    
    # Tipos de documento (NO son roles) - aparecen cerca de la descripción
    DOCUMENT_TYPE_PATTERNS = {
        'DC': [r'\bdc\b', r'documento', r'document'],
        'PL': [r'\bpl\b', r'plano', r'drawing'],
        'GL': [r'\bgl\b', r'global', r'general'],
    }
    
    # Disciplinas conocidas
    DISCIPLINAS = [
        'piping', 'mecanica', 'mecánica', 'mechanical',
        'electrica', 'eléctrica', 'electrical',
        'civil', 'estructural', 'structural',
        'instrumentacion', 'instrumentación', 'i&c', 'control',
        'proceso', 'process',
        'hvac', 'climatizacion',
        'arquitectura', 'architecture'
    ]
    
    # Keywords para ignorar filas
    SKIP_KEYWORDS = ['subtotal', 'sub-total', 'total general', 'total final', 
                     'suma', 'resumen', 'notas', 'notes', 'n/a']
    
    def __init__(self, df: pd.DataFrame, use_ai: bool = False, ai_helper=None):
        """
        Args:
            df: DataFrame con los datos de la hoja Excel (sin header)
            use_ai: Si usar IA para limpiar roles no reconocidos
            ai_helper: Instancia de AIHelper (opcional)
        """
        self.df = df
        self.use_ai = use_ai
        self.ai = ai_helper
        self.header_info: Optional[HeaderInfo] = None
        
    def extract(self) -> Tuple[List[Dict], HeaderInfo]:
        """
        Extrae los datos de la tabla HH.
        
        Returns:
            Tuple[List[Dict], HeaderInfo]: (filas extraídas, info del header)
        """
        # FASE 1: Detectar headers
        self.header_info = self._detect_headers()
        
        if not self.header_info or self.header_info.start_row == -1:
            print("   ❌ No se detectó encabezado válido")
            return [], None
        
        print(f"   📋 Header detectado en fila(s) {self.header_info.start_row}"
              f"{'-'+str(self.header_info.end_row) if self.header_info.is_multi_row else ''}")
        print(f"   📊 Columnas: {len(self.header_info.columns)}")
        
        # Mostrar columnas detectadas
        roles_detected = [c for c in self.header_info.columns if c.col_type == 'role']
        if roles_detected:
            roles_str = ', '.join([f"{c.name}→{c.role_code}" for c in roles_detected[:5]])
            print(f"   👥 Roles: {roles_str}{'...' if len(roles_detected) > 5 else ''}")
        
        # FASE 2: Extraer datos
        rows = self._extract_data()
        
        print(f"   ✅ Filas extraídas: {len(rows)}")
        
        return rows, self.header_info
    
    def _detect_headers(self) -> HeaderInfo:
        """
        Detecta la fila (o filas) de encabezado.
        
        Estrategia:
        1. Buscar fila con keywords de header (item, descripción, etc.)
        2. Verificar si hay una segunda fila de headers (códigos de roles)
        3. Clasificar cada columna por tipo
        """
        header_row_idx = -1
        
        # Buscar en primeras 20 filas
        for idx in range(min(20, len(self.df))):
            row = self.df.iloc[idx]
            row_text = ' '.join(str(x).lower() for x in row if pd.notna(x))
            
            # ¿Contiene keywords de header?
            if any(kw in row_text for kw in self.HEADER_KEYWORDS):
                header_row_idx = idx
                break
        
        if header_row_idx == -1:
            return HeaderInfo(start_row=-1, end_row=-1, is_multi_row=False, data_start_row=0)
        
        # Analizar la fila de header
        header_row = self.df.iloc[header_row_idx]
        
        # Verificar si hay una segunda fila de headers (multi-línea)
        is_multi_row = False
        second_header_row = None
        
        if header_row_idx + 1 < len(self.df):
            next_row = self.df.iloc[header_row_idx + 1]
            
            # Contar cuántas celdas parecen códigos de rol (2-4 chars alfanuméricos)
            role_like_count = 0
            for val in next_row:
                if pd.notna(val):
                    val_str = str(val).strip()
                    if 2 <= len(val_str) <= 5 and val_str.replace(' ', '').isalnum():
                        # Verificar si matchea algún patrón de rol
                        if self._match_role(val_str) != 'UNKNOWN':
                            role_like_count += 1
            
            # Si hay al menos 3 columnas que parecen roles, es multi-línea
            if role_like_count >= 3:
                is_multi_row = True
                second_header_row = next_row
                print(f"   📋 Header multi-línea detectado (fila {header_row_idx} + {header_row_idx + 1})")
        
        # Construir información de columnas
        columns = self._analyze_columns(header_row, second_header_row if is_multi_row else None)
        
        end_row = header_row_idx + 1 if is_multi_row else header_row_idx
        data_start = end_row + 1
        
        return HeaderInfo(
            start_row=header_row_idx,
            end_row=end_row,
            is_multi_row=is_multi_row,
            columns=columns,
            data_start_row=data_start
        )
    
    def _analyze_columns(self, header_row: pd.Series, second_row: Optional[pd.Series] = None) -> List[ColumnInfo]:
        """
        Analiza las columnas y las clasifica por tipo.
        
        REGLA IMPORTANTE: 
        - Columnas cerca de la descripción (DC, PL, GL) son TIPOS DE DOCUMENTO
        - Columnas de roles (JP, JD, IA, IB, etc.) vienen DESPUÉS
        - Si una columna está ANTES de JD, NO es rol de Control de Documentos
        
        Args:
            header_row: Primera fila del header
            second_row: Segunda fila del header (si es multi-línea)
        """
        columns = []
        
        # Obtener algunas filas de datos para analizar tipos
        data_start = self.header_info.data_start_row if self.header_info else 3
        sample_rows = self.df.iloc[data_start:data_start + 5]
        
        # PASO 1: Primera pasada - encontrar posiciones clave
        desc_col_idx = -1
        first_role_col_idx = -1  # Primera columna que parece rol (JP, JD, etc.)
        
        for col_idx in range(len(header_row)):
            val1 = header_row.iloc[col_idx] if col_idx < len(header_row) else None
            val2 = second_row.iloc[col_idx] if second_row is not None and col_idx < len(second_row) else None
            
            col_name = ""
            if pd.notna(val2) and str(val2).strip():
                col_name = str(val2).strip().lower()
            elif pd.notna(val1) and str(val1).strip():
                col_name = str(val1).strip().lower()
            
            # Detectar columna de descripción
            if any(kw in col_name for kw in ['descripcion', 'descripción', 'actividad', 'entregable']):
                desc_col_idx = col_idx
            
            # Detectar primera columna de rol real (JP o JD)
            if first_role_col_idx == -1:
                if re.search(r'\bjp\b|\bjd\b', col_name):
                    first_role_col_idx = col_idx
        
        # PASO 2: Segunda pasada - clasificar columnas con contexto de posición
        for col_idx in range(len(header_row)):
            val1 = header_row.iloc[col_idx] if col_idx < len(header_row) else None
            val2 = second_row.iloc[col_idx] if second_row is not None and col_idx < len(second_row) else None
            
            # Determinar el nombre de la columna
            if pd.notna(val2) and str(val2).strip():
                col_name = str(val2).strip()
                parent_name = str(val1).strip() if pd.notna(val1) else None
            elif pd.notna(val1) and str(val1).strip():
                col_name = str(val1).strip()
                parent_name = None
            else:
                continue  # Columna vacía, ignorar
            
            # Analizar tipo de dato en las filas de datos
            sample_values = []
            numeric_count = 0
            text_count = 0
            
            for _, data_row in sample_rows.iterrows():
                if col_idx < len(data_row):
                    val = data_row.iloc[col_idx]
                    if pd.notna(val):
                        sample_values.append(val)
                        try:
                            float(val)
                            numeric_count += 1
                        except:
                            text_count += 1
            
            # Determinar data_type
            if numeric_count > text_count:
                data_type = 'numeric'
            elif text_count > numeric_count:
                data_type = 'text'
            else:
                data_type = 'mixed'
            
            # Determinar si está ANTES de los roles (zona de tipos de documento)
            is_before_roles = first_role_col_idx > 0 and col_idx < first_role_col_idx
            
            # Clasificar tipo de columna
            col_type, role_code, disciplina = self._classify_column(
                col_name, parent_name, data_type, 
                is_before_roles=is_before_roles
            )
            
            columns.append(ColumnInfo(
                idx=col_idx,
                name=col_name,
                col_type=col_type,
                role_code=role_code,
                disciplina=disciplina,
                data_type=data_type,
                sample_values=sample_values[:3]
            ))
        
        return columns
    
    def _classify_column(self, col_name: str, parent_name: Optional[str], data_type: str, 
                         is_before_roles: bool = False) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Clasifica una columna por su tipo.
        
        REGLA CLAVE: Si is_before_roles=True y la columna es DC/PL/GL,
        es TIPO DE DOCUMENTO, no rol profesional.
        
        Returns:
            Tuple[col_type, role_code, disciplina]
        """
        col_lower = col_name.lower()
        col_upper = col_name.upper().strip()
        
        # 1. Verificar si es columna de ITEM (pero NO si contiene "actividad" o "documento")
        if any(kw in col_lower for kw in ['item', 'ítem', 'codigo', 'código', 'id', 'n°', 'nº']):
            # Verificar que NO sea también descripción
            if not any(kw in col_lower for kw in ['actividad', 'documento', 'descripcion', 'descripción']):
                return 'item', None, None
        
        # 2. Verificar si es columna de DESCRIPCIÓN (incluye actividad, documento, etc.)
        if any(kw in col_lower for kw in ['descripcion', 'descripción', 'actividad', 'documento', 
                                           'entregable', 'plano', 'deliverable', 'activity', 'tarea']):
            return 'description', None, None
        
        # 3. Verificar si es columna de CANTIDAD
        if any(kw in col_lower for kw in ['cantidad', 'qty', 'quantity', 'cant', 'ud', 'unidad']):
            return 'quantity', None, None
        
        # 4. Verificar si es columna de TOTAL
        if any(kw in col_lower for kw in ['total', 'suma', 'sum']):
            return 'total', None, None
        
        # 5. REGLA ESPECIAL: Si está ANTES de los roles, verificar si es tipo de documento
        if is_before_roles:
            doc_type = self._match_document_type(col_name)
            if doc_type:
                return 'doc_type', doc_type, None
        
        # 6. Verificar si es ROL profesional
        role_code = self._match_role(col_name)
        if role_code != 'UNKNOWN':
            # Buscar disciplina en el nombre
            disciplina = self._extract_disciplina(col_name)
            if not disciplina and parent_name:
                disciplina = self._extract_disciplina(parent_name)
            return 'role', role_code, disciplina
        
        # 7. Si es numérico y no matchea nada, podría ser un rol no reconocido
        if data_type == 'numeric' and len(col_name) <= 20:
            # NO convertir automáticamente si está antes de roles
            if is_before_roles:
                return 'doc_type', col_upper[:4], None
            
            # Intentar usar IA si está disponible
            if self.use_ai and self.ai:
                try:
                    role_code, confidence = self.ai.normalize_role(col_name)
                    if confidence > 0.7:
                        disciplina = self._extract_disciplina(col_name)
                        return 'role', role_code, disciplina
                except:
                    pass
            
            # Marcar como rol desconocido para revisión
            return 'role', col_name.upper()[:4], self._extract_disciplina(col_name)
        
        return 'unknown', None, None
    
    def _match_document_type(self, text: str) -> Optional[str]:
        """Matchea texto contra patrones de tipos de documento."""
        if not text:
            return None
        
        text_lower = text.lower().strip()
        
        for doc_type, patterns in self.DOCUMENT_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return doc_type
        
        return None
    
    def _match_role(self, text: str) -> str:
        """Matchea texto contra patrones de roles conocidos."""
        if not text or len(text) > 50:
            return 'UNKNOWN'
        
        text_lower = text.lower().strip()
        
        for role_code, patterns in self.ROLE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return role_code
        
        return 'UNKNOWN'
    
    def _extract_disciplina(self, text: str) -> Optional[str]:
        """Extrae disciplina mencionada en el texto."""
        if not text:
            return None
        
        text_lower = text.lower()
        
        for disc in self.DISCIPLINAS:
            if disc in text_lower:
                # Normalizar nombre
                if disc in ['mecanica', 'mecánica', 'mechanical']:
                    return 'Mecánica'
                elif disc in ['electrica', 'eléctrica', 'electrical']:
                    return 'Eléctrica'
                elif disc in ['civil', 'estructural', 'structural']:
                    return 'Civil'
                elif disc in ['instrumentacion', 'instrumentación', 'i&c', 'control']:
                    return 'Instrumentación'
                elif disc in ['proceso', 'process']:
                    return 'Proceso'
                elif disc in ['hvac', 'climatizacion']:
                    return 'HVAC'
                elif disc in ['arquitectura', 'architecture']:
                    return 'Arquitectura'
                elif disc == 'piping':
                    return 'Piping'
        
        return None
    
    def _extract_data(self) -> List[Dict]:
        """
        Extrae los datos de las filas.
        """
        if not self.header_info or self.header_info.start_row == -1:
            return []
        
        # Identificar columnas clave
        item_col = next((c for c in self.header_info.columns if c.col_type == 'item'), None)
        desc_col = next((c for c in self.header_info.columns if c.col_type == 'description'), None)
        qty_col = next((c for c in self.header_info.columns if c.col_type == 'quantity'), None)
        role_cols = [c for c in self.header_info.columns if c.col_type == 'role']
        
        if not desc_col:
            print("   ⚠️ No se encontró columna de descripción")
            return []
        
        rows = []
        empty_count = 0
        
        for idx in range(self.header_info.data_start_row, len(self.df)):
            row = self.df.iloc[idx]
            
            # Obtener descripción
            desc = None
            if desc_col and desc_col.idx < len(row):
                val = row.iloc[desc_col.idx]
                if pd.notna(val):
                    desc = str(val).strip()
            
            # Verificar si es fila válida
            if not desc or len(desc) < 2:
                empty_count += 1
                if empty_count >= 5:
                    break  # Demasiadas filas vacías, terminar
                continue
            
            # Verificar si debe ser ignorada
            if self._should_skip(desc):
                continue
            
            empty_count = 0
            
            # Obtener item
            item = None
            if item_col and item_col.idx < len(row):
                val = row.iloc[item_col.idx]
                if pd.notna(val):
                    item = str(val).strip()
            
            # Obtener cantidad
            cantidad = None
            if qty_col and qty_col.idx < len(row):
                val = row.iloc[qty_col.idx]
                if pd.notna(val):
                    try:
                        cantidad = float(val)
                    except:
                        pass
            
            # Obtener HH por rol
            man_hours = {}
            for role_col in role_cols:
                if role_col.idx < len(row):
                    val = row.iloc[role_col.idx]
                    if pd.notna(val):
                        try:
                            hh = float(val)
                            if hh > 0:
                                key = role_col.role_code
                                if role_col.disciplina:
                                    key = f"{role_col.role_code}_{role_col.disciplina}"
                                man_hours[key] = hh
                        except:
                            pass
            
            # Detectar si es fila padre (título de sección)
            is_parent = False
            level = 0
            if item:
                if item.endswith('.0') or item.endswith('.00'):
                    is_parent = len(man_hours) == 0  # Padre si no tiene HH
                    level = 0
                else:
                    level = item.count('.')
            
            rows.append({
                'item': item,
                'description': desc,
                'cantidad': cantidad,
                'man_hours': man_hours,
                'total_hh': sum(man_hours.values()),
                'is_parent': is_parent,
                'level': level
            })
        
        return rows
    
    def _should_skip(self, text: str) -> bool:
        """Verifica si una fila debe ser ignorada."""
        if not text:
            return True
        
        text_lower = text.lower().strip()
        return any(kw in text_lower for kw in self.SKIP_KEYWORDS)


def extract_hh_table(df: pd.DataFrame, use_ai: bool = False, ai_helper=None) -> Tuple[List[Dict], Optional[HeaderInfo]]:
    """
    Función de conveniencia para extraer tabla HH.
    
    Args:
        df: DataFrame de la hoja Excel (sin header)
        use_ai: Si usar IA para roles no reconocidos
        ai_helper: Instancia de AIHelper
    
    Returns:
        Tuple[List[Dict], HeaderInfo]
    """
    extractor = HHTableExtractor(df, use_ai, ai_helper)
    return extractor.extract()
