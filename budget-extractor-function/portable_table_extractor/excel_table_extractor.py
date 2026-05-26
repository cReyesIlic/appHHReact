"""
ExcelTableExtractor - Motor portable de extracción de tablas desde Excel
Versión simplificada y fácil de integrar en cualquier proyecto
"""
import pandas as pd
import time
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime

from .schemas import TableType, ExtractedTable, ExcelProcessingResult
from .config import (
    SHEET_NAME_KEYWORDS, ROLE_PATTERNS, COLUMN_KEYWORDS, ITEM_TYPE_SYNONYMS,
    match_role_pattern, is_hierarchy_code, should_skip_row, THRESHOLDS,
    normalize_number, normalize_column_name, infer_item_type_from_description,
    match_item_type, match_column_type, is_document_type_column
)
from .ai_helper import AIHelper
from .hh_table_extractor import HHTableExtractor, extract_hh_table


class ExcelTableExtractor:
    """
    Extractor inteligente de tablas desde archivos Excel
    
    Características:
    - Clasificación automática de tipo de tabla
    - Detección dinámica de headers
    - Normalización de roles profesionales
    - Uso opcional de IA como fallback
    
    Uso:
        extractor = ExcelTableExtractor("archivo.xlsx", use_ai=True)
        result = extractor.process()
        
        for table in result.tables:
            print(f"{table.sheet_name}: {table.num_rows} filas")
    """
    
    def __init__(self, file_path: str, use_ai: bool = True, ai_model: str = "gpt-4o-mini", openai_api_key: str = None):
        """
        Args:
            file_path: Ruta al archivo Excel
            use_ai: Activar IA como fallback (requiere OpenAI API key)
            ai_model: Modelo de IA (por defecto gpt-4o-mini)
            openai_api_key: API key de OpenAI (opcional, puede usar variable de entorno)
        """
        self.file_path = Path(file_path)
        self.file_name = self.file_path.name
        
        if not self.file_path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
        
        # Cargar Excel
        try:
            self.xl = pd.ExcelFile(str(self.file_path))
        except Exception as e:
            raise ValueError(f"Error leyendo Excel: {e}")
        
        # Inicializar IA si está habilitada
        self.use_ai = use_ai
        self.ai = None
        if use_ai:
            try:
                self.ai = AIHelper(model=ai_model, api_key=openai_api_key)
            except Exception as e:
                print(f"⚠️ No se pudo inicializar IA: {e}")
                self.use_ai = False
        
        # Estadísticas
        self.stats = {
            "sheets_total": len(self.xl.sheet_names),
            "sheets_processed": 0,
            "sheets_skipped": 0,
            "tables_extracted": 0,
            "errors": []
        }
    
    def process(self) -> ExcelProcessingResult:
        """
        Procesa todas las hojas del Excel
        
        Returns:
            ExcelProcessingResult con todas las tablas extraídas
        """
        print(f"\n{'='*80}")
        print(f"📊 PROCESANDO: {self.file_name}")
        print(f"{'='*80}")
        print(f"📄 Hojas totales: {len(self.xl.sheet_names)}")
        
        start_time = time.time()
        tables: List[ExtractedTable] = []
        
        for idx, sheet_name in enumerate(self.xl.sheet_names, 1):
            print(f"\n[{idx}/{len(self.xl.sheet_names)}] 🔍 {sheet_name}")
            
            try:
                df = pd.read_excel(self.file_path, sheet_name=sheet_name, header=None)
                
                if df.empty:
                    print(f"   ⏭️  Hoja vacía")
                    self.stats["sheets_skipped"] += 1
                    continue
                
                # Clasificar tipo de tabla
                table_type, confidence, method = self._classify_sheet(sheet_name, df)
                
                if table_type == TableType.UNKNOWN:
                    print(f"   ❓ Tipo desconocido, omitiendo")
                    self.stats["sheets_skipped"] += 1
                    continue
                
                print(f"   ✅ {table_type.value} (confianza: {confidence:.2f})")
                
                # Extraer datos
                extracted_table = self._extract_table(sheet_name, df, table_type, confidence, method)
                
                if extracted_table and extracted_table.num_rows > 0:
                    tables.append(extracted_table)
                    self.stats["tables_extracted"] += 1
                    self.stats["sheets_processed"] += 1
                    print(f"   📊 {extracted_table.num_rows} filas extraídas")
                else:
                    print(f"   ⚠️  Sin datos válidos")
                    self.stats["sheets_skipped"] += 1
            
            except Exception as e:
                error_msg = f"Error en '{sheet_name}': {str(e)}"
                print(f"   ❌ {error_msg}")
                self.stats["errors"].append(error_msg)
                self.stats["sheets_skipped"] += 1
        
        processing_time = time.time() - start_time
        
        # Contadores por tipo
        tables_entregables = sum(1 for t in tables if t.table_type == TableType.ENTREGABLES)
        tables_tarifas = sum(1 for t in tables if t.table_type == TableType.TARIFAS)
        tables_gastos = sum(1 for t in tables if t.table_type == TableType.GASTOS)
        tables_other = len(tables) - tables_entregables - tables_tarifas - tables_gastos
        
        print(f"\n{'='*80}")
        print(f"✅ COMPLETADO")
        print(f"{'='*80}")
        print(f"⏱️  {processing_time:.2f}s")
        print(f"📊 Tablas: {len(tables)} (Entregables:{tables_entregables} Tarifas:{tables_tarifas} Gastos:{tables_gastos})")
        if self.use_ai and self.ai:
            print(f"🤖 Llamadas IA: {self.ai.call_count}")
        
        return ExcelProcessingResult(
            file_path=str(self.file_path),
            file_name=self.file_name,
            tables=tables,
            total_sheets=self.stats["sheets_total"],
            sheets_processed=self.stats["sheets_processed"],
            sheets_skipped=self.stats["sheets_skipped"],
            tables_entregables=tables_entregables,
            tables_tarifas=tables_tarifas,
            tables_gastos=tables_gastos,
            tables_other=tables_other,
            errors=self.stats["errors"],
            processing_time_seconds=processing_time,
            processed_at=datetime.now().isoformat()
        )
    
    def _classify_sheet(self, sheet_name: str, df: pd.DataFrame) -> Tuple[TableType, float, str]:
        """Clasifica el tipo de tabla"""
        # 1. Heurística por nombre
        table_type = self._classify_by_name(sheet_name)
        if table_type != TableType.UNKNOWN:
            return table_type, 0.85, "heuristic"
        
        # 2. Análisis de contenido
        table_type, confidence = self._classify_by_content(df)
        if confidence >= THRESHOLDS["min_confidence_heuristic"]:
            return table_type, confidence, "content"
        
        # 3. Fallback a IA
        if self.use_ai and self.ai:
            print(f"      🤖 Consultando IA...")
            snippet = df.head(15).to_csv(index=False)
            table_type_str, confidence = self.ai.classify_sheet(sheet_name, snippet)
            if confidence >= THRESHOLDS["min_confidence_ai"]:
                try:
                    return TableType(table_type_str), confidence, "ai"
                except:
                    pass
        
        return TableType.UNKNOWN, 0.0, "failed"
    
    def _classify_by_name(self, sheet_name: str) -> TableType:
        """Clasificación rápida por nombre de hoja"""
        name_lower = sheet_name.lower().strip()
        
        for table_type_str, keywords in SHEET_NAME_KEYWORDS.items():
            if any(kw in name_lower for kw in keywords):
                try:
                    return TableType(table_type_str)
                except:
                    continue
        
        return TableType.UNKNOWN
    
    def _classify_by_content(self, df: pd.DataFrame) -> Tuple[TableType, float]:
        """Clasificación por contenido"""
        sample_text = " ".join(df.head(10).astype(str).values.flatten()).lower()
        
        scores = {}
        for table_type_str, keywords in SHEET_NAME_KEYWORDS.items():
            score = sum(sample_text.count(kw) for kw in keywords)
            if score > 0:
                scores[table_type_str] = score
        
        if not scores:
            return TableType.UNKNOWN, 0.0
        
        best_type = max(scores, key=scores.get)
        confidence = min(0.9, 0.5 + (scores[best_type] * 0.1))
        
        try:
            return TableType(best_type), confidence
        except:
            return TableType.UNKNOWN, 0.0
    
    def _extract_table(self, sheet_name: str, df: pd.DataFrame, table_type: TableType, 
                       confidence: float, method: str) -> Optional[ExtractedTable]:
        """Extrae datos según el tipo de tabla"""
        start_time = time.time()
        
        try:
            if table_type == TableType.ENTREGABLES:
                data = self._extract_deliverables(df)
            elif table_type == TableType.TARIFAS:
                data = self._extract_rates(df)
            elif table_type == TableType.GASTOS:
                data = self._extract_expenses(df)
            else:
                data = self._extract_generic(df)
            
            if not data:
                return None
            
            return ExtractedTable(
                sheet_name=sheet_name,
                table_type=table_type,
                confidence=confidence,
                data=data,
                detection_method=method,
                processing_time_seconds=time.time() - start_time,
                metadata={"original_shape": list(df.shape)}
            )
        
        except Exception as e:
            print(f"      ❌ Error extrayendo: {e}")
            return None
    
    def _find_header_row(self, df: pd.DataFrame, keywords: List[str] = None) -> Tuple[int, Dict, int]:
        """Encuentra la fila de headers - soporta multi-fila
        Retorna: (header_idx, col_map, rows_to_skip)
        """
        keywords = keywords or ["item", "descripcion", "descripción", "ítem"]
        
        # Normalizar keywords para búsqueda sin tildes
        def remove_accents(text):
            import unicodedata
            return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
        
        keywords_normalized = [remove_accents(kw) for kw in keywords]
        
        for idx, row in df.head(20).iterrows():
            row_text = " ".join(str(x).lower() for x in row if pd.notna(x))
            row_text_norm = remove_accents(row_text)
            
            if any(kw in row_text for kw in keywords) or any(kw in row_text_norm for kw in keywords_normalized):
                # Crear mapeo de columnas desde esta fila
                col_map = {}
                main_headers = row

                rows_to_skip = 1
                # Verificar siguiente fila por columnas de roles adicionales (multi-header)
                if idx + 1 < len(df):
                    next_row = df.iloc[idx + 1]
                    added_from_next = False

                    # Procesar ambas filas juntas con priorización
                    for col_idx in range(len(main_headers)):
                        main_val = main_headers.iloc[col_idx] if pd.notna(main_headers.iloc[col_idx]) else ""
                        role_val = next_row.iloc[col_idx] if pd.notna(next_row.iloc[col_idx]) else ""

                        main_str = normalize_column_name(str(main_val))
                        role_str = str(role_val).strip().upper()

                        # PRIORIDAD 1: Columnas estructurales desde main_str
                        if "ITEM" in main_str.upper() or "ÍTEM" in main_str.upper():
                            col_map[col_idx] = "Código"
                        elif "ACTIVIDAD" in main_str.upper() or "DESCRIPCION" in main_str.upper() or "DESCRIPCIÓN" in main_str.upper():
                            col_map[col_idx] = "Descripción"
                        elif "CANTIDAD" in main_str.upper():
                            col_map[col_idx] = "Cantidad"
                        # PRIORIDAD 2: Tipos de documento desde role_str (ANTES de roles)
                        elif role_str and len(role_str) > 0:
                            doc_type = is_document_type_column(role_str)
                            if doc_type:
                                col_map[col_idx] = doc_type
                                added_from_next = True
                            else:
                                # PRIORIDAD 3: Roles profesionales
                                matched_role = match_role_pattern(role_str)
                                if matched_role != "UNKNOWN":
                                    col_map[col_idx] = matched_role
                                    added_from_next = True
                                elif len(role_str) <= 5 and role_str.replace(" ", "").isalnum():
                                    col_map[col_idx] = role_str
                                    added_from_next = True
                                elif main_val and len(str(main_val).strip()) > 1:
                                    col_map[col_idx] = str(main_val).strip()
                        elif main_val and len(str(main_val).strip()) > 1:
                            col_map[col_idx] = str(main_val).strip()

                    # Si añadimos columnas de la siguiente fila, debemos saltarla también
                    if added_from_next:
                        rows_to_skip = 2
                else:
                    # Solo una fila de headers
                    for col_idx, val in enumerate(row):
                        if pd.notna(val):
                            col_name = str(val).strip()
                            if len(col_name) > 1:
                                col_map[col_idx] = col_name
                
                return idx, col_map, rows_to_skip
        
        return -1, {}, 0
    
    def _extract_deliverables(self, df: pd.DataFrame) -> List[Dict]:
        """
        Extrae tabla de entregables con enfoque DETERMINÍSTICO.
        
        FLUJO:
        1. Detectar headers (single o multi-línea) analizando filas
        2. Clasificar columnas por tipo de dato (texto vs número)
        3. Extraer datos determinísticamente
        4. Usar IA SOLO para limpiar/normalizar roles no reconocidos
        """
        print("      📊 Usando extractor determinístico HHTableExtractor...")
        
        # Usar el nuevo extractor determinístico
        extractor = HHTableExtractor(df, use_ai=self.use_ai, ai_helper=self.ai)
        rows, header_info = extractor.extract()
        
        if not rows:
            print("      ⚠️ HHTableExtractor no encontró datos")
            # Fallback al método simple
            return self._extract_deliverables_simple(df)
        
        # Convertir al formato esperado
        data = []
        for row in rows:
            # Determinar tipo de ítem desde descripción
            desc = row.get("description", "")
            item_type = infer_item_type_from_description(desc) if desc else "DESCONOCIDO"
            
            # Construir observaciones
            observations = []
            if row.get("is_parent"):
                observations.append("Título de sección (padre)")
            if not row.get("man_hours"):
                observations.append("Sin horas asignadas")
            
            # Extraer disciplinas detectadas de los man_hours
            disciplinas = set()
            for key in row.get("man_hours", {}).keys():
                if "_" in key:
                    disc = key.split("_")[1]
                    disciplinas.add(disc)
            
            data.append({
                "item": row.get("item", ""),
                "description": desc,
                "item_type": item_type,
                "cantidad": row.get("cantidad") or 1,
                "disciplina": ", ".join(disciplinas) if disciplinas else "General",
                "etapa": "",
                "man_hours": row.get("man_hours", {}),
                "total_hh": row.get("total_hh", 0),
                "is_parent": row.get("is_parent", False),
                "level": row.get("level", 0),
                "confidence": 0.85,  # Alta confianza para método determinístico
                "observations": observations
            })
        
        return data
    
    def _extract_deliverables_simple(self, df: pd.DataFrame) -> List[Dict]:
        """Método simple de fallback para extracción"""
        header_idx, col_map, rows_to_skip = self._find_header_row(
            df, 
            ["item", "ítem", "descripcion", "descripción", "entregable", "actividad", "documento", "plano"]
        )
        
        if header_idx == -1:
            return []
        
        data = []
        data_rows = df.iloc[header_idx + rows_to_skip:].reset_index(drop=True)
        
        for idx, row in data_rows.iterrows():
            # Buscar columna item y descripción
            item = None
            desc = None
            cantidad = None
            man_hours = {}
            
            for col_idx, col_name in col_map.items():
                if col_idx >= len(row):
                    continue
                
                val = row.iloc[col_idx]
                col_lower = col_name.lower()
                
                # Normalizar nombre de columna
                col_normalized = normalize_column_name(col_name)
                col_type = match_column_type(col_normalized)

                # Identificar columnas clave
                if col_type == "ITEM" or "item" in col_lower or "ítem" in col_lower:
                    item = str(val) if pd.notna(val) else None
                elif col_type == "DESCRIPTION" or any(kw in col_lower for kw in ["descripcion", "descripción", "entregable", "actividad"]):
                    desc = str(val) if pd.notna(val) else None
                elif col_type == "QUANTITY" or "cantidad" in col_lower:
                    cantidad = normalize_number(val)
                elif col_type in ["DOCUMENT", "DRAWING", "ACTIVITY"]:
                    # Columnas de tipo de ítem (DC, PL, GL)
                    type_val = normalize_number(val)
                    if type_val > 0:
                        # Agregar a metadata o man_hours según sea necesario
                        pass
                else:
                    # PRIORIDAD 1: Verificar si es tipo de documento ANTES de roles
                    doc_type = is_document_type_column(col_name)
                    if doc_type:
                        # Es columna de tipo (DC, PL, GL), no de horas
                        pass
                    else:
                        # PRIORIDAD 2: Intentar detectar si es una columna de rol
                        role_code = match_role_pattern(col_name)
                        if role_code != "UNKNOWN":
                            hh = normalize_number(val)  # Usar normalize_number en vez de pd.to_numeric
                            if hh > 0:
                                man_hours[role_code] = hh
            
            # Validar fila
            if desc and len(desc) > 3 and not should_skip_row(desc):
                # Inferir tipo de ítem desde descripción
                item_type = infer_item_type_from_description(desc)

                # Análisis semántico de la descripción con IA
                disciplina = "General"
                etapa = ""
                confidence = 0.7  # Confianza base para método determinista
                observations = []

                if self.use_ai and self.ai and len(desc) > 10:
                    try:
                        analysis = self.ai.analyze_deliverable_description(desc)
                        if analysis["confidence"] > 0.6:
                            disciplina = ", ".join(analysis["disciplinas"])
                            etapa = analysis["etapa"]
                            confidence = analysis["confidence"]
                            observations.append(f"IA detectó disciplina: {disciplina}")
                    except:
                        observations.append("IA no disponible, usando valores por defecto")

                # Agregar observaciones sobre detección
                if item_type != "DESCONOCIDO":
                    observations.append(f"Tipo inferido de descripción: {item_type}")
                if len(man_hours) == 0:
                    observations.append("Sin horas asignadas")
                    confidence *= 0.8
                if not item:
                    observations.append("Sin código de ítem")
                    confidence *= 0.9

                data.append({
                    "item": item or "",
                    "description": desc,
                    "item_type": item_type,
                    "cantidad": cantidad if cantidad and cantidad > 0 else 1,
                    "disciplina": disciplina,
                    "etapa": etapa,
                    "man_hours": man_hours,
                    "total_hh": sum(man_hours.values()),
                    "confidence": confidence,
                    "observations": observations
                })
            
            # Limitar filas vacías consecutivas
            if len(data) > 0 and not desc:
                if idx - len(data) > 10:
                    break
        
        return data
    
    def _extract_rates(self, df: pd.DataFrame) -> List[Dict]:
        """Extrae tabla de tarifas"""
        header_idx, col_map, rows_to_skip = self._find_header_row(df, ["tarifa", "rate", "rol", "precio"])
        
        if header_idx == -1:
            return []
        
        data = []
        data_rows = df.iloc[header_idx + rows_to_skip:].reset_index(drop=True)
        
        for _, row in data_rows.iterrows():
            role = None
            rate = None
            currency = "CLP"
            
            for col_idx, col_name in col_map.items():
                if col_idx >= len(row):
                    continue
                
                val = row.iloc[col_idx]
                col_lower = col_name.lower()
                
                if "rol" in col_lower or "cargo" in col_lower or "categoria" in col_lower:
                    role = str(val) if pd.notna(val) else None
                elif "tarifa" in col_lower or "rate" in col_lower or "precio" in col_lower:
                    rate = pd.to_numeric(val, errors='coerce')
                elif "moneda" in col_lower or "currency" in col_lower:
                    currency = str(val) if pd.notna(val) else "CLP"
            
            if role and rate and rate > 0:
                role_code = match_role_pattern(role)
                data.append({
                    "role_code": role_code,
                    "original_description": role,
                    "rate": float(rate),
                    "currency": currency
                })
        
        return data
    
    def _extract_expenses(self, df: pd.DataFrame) -> List[Dict]:
        """Extrae tabla de gastos"""
        header_idx, col_map, rows_to_skip = self._find_header_row(df, ["gasto", "descripcion", "cantidad"])
        
        if header_idx == -1:
            return []
        
        data = []
        data_rows = df.iloc[header_idx + rows_to_skip:].reset_index(drop=True)
        
        for _, row in data_rows.iterrows():
            desc = None
            qty = None
            price = None
            total = None
            
            for col_idx, col_name in col_map.items():
                if col_idx >= len(row):
                    continue
                
                val = row.iloc[col_idx]
                col_lower = col_name.lower()
                
                if "descripcion" in col_lower or "descripción" in col_lower or "gasto" in col_lower:
                    desc = str(val) if pd.notna(val) else None
                elif "cantidad" in col_lower or "qty" in col_lower:
                    qty = pd.to_numeric(val, errors='coerce')
                elif "precio" in col_lower or "unitario" in col_lower:
                    price = pd.to_numeric(val, errors='coerce')
                elif "total" in col_lower:
                    total = pd.to_numeric(val, errors='coerce')
            
            if desc and (qty or total):
                data.append({
                    "description": desc,
                    "quantity": float(qty) if qty else 0,
                    "unit_price": float(price) if price else 0,
                    "total": float(total) if total else (qty * price if qty and price else 0)
                })
        
        return data
    
    def _extract_generic(self, df: pd.DataFrame) -> List[Dict]:
        """Extracción genérica para tipos no reconocidos"""
        header_idx, col_map, rows_to_skip = self._find_header_row(df)
        
        if header_idx == -1:
            return []
        
        data = []
        data_rows = df.iloc[header_idx + rows_to_skip:header_idx + rows_to_skip + 50].reset_index(drop=True)
        
        for _, row in data_rows.iterrows():
            row_dict = {}
            for col_idx, col_name in col_map.items():
                if col_idx < len(row):
                    val = row.iloc[col_idx]
                    if pd.notna(val):
                        row_dict[col_name] = val
            
            if row_dict:
                data.append(row_dict)
        
        return data
