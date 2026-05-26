"""
AI Helper - Asistente de IA para casos ambiguos
Solo se usa cuando la lógica determinística falla
"""
import json
from typing import Optional, Tuple, Dict
from openai import AzureOpenAI
import os


class AIHelper:
    """Asistente de IA que resuelve ambigüedades"""
    
    def __init__(self, model: str = None, api_key: str = None, azure_endpoint: str = None, api_version: str = None):
        # Intentar Azure OpenAI primero
        azure_endpoint = azure_endpoint or os.getenv('AZURE_OPENAI_ENDPOINT')
        api_key = api_key or os.getenv('AZURE_OPENAI_API_KEY')
        api_version = api_version or os.getenv('AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        
        # Para Azure, usar el deployment name desde env
        self.model = model or os.getenv('AZURE_DEPLOYMENT_GPT4O_MINI', 'gpt-4o-mini')
        
        if azure_endpoint and api_key:
            self.client = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=azure_endpoint
            )
            self.is_azure = True
            print(f"✅ Azure OpenAI configurado - deployment: {self.model}")
        else:
            raise ValueError("Azure OpenAI credentials required")
        
        self.call_count = 0
    
    def classify_sheet(self, sheet_name: str, sample_data: str) -> Tuple[str, float]:
        """
        Clasifica el tipo de hoja cuando es ambiguo
        
        Returns:
            (table_type, confidence)
        """
        self.call_count += 1
        
        prompt = f"""Eres experto en análisis de documentos de ingeniería.

Analiza esta hoja Excel de un PROYECTO DE INGENIERÍA y determina qué tipo de tabla es.

NOMBRE HOJA: "{sheet_name}"

CONTENIDO (primeras filas):
{sample_data[:2000]}

=== TIPOS DE TABLAS EN PROYECTOS DE INGENIERÍA ===

1. entregables_profesionales:
   • OBJETIVO: Planificar dotación de profesionales por entregable/actividad
   • ESTRUCTURA: Matriz de entregables vs horas-hombre (HH) por profesional
   • COLUMNAS TÍPICAS:
     - ÍTEM/ITEM: Código jerárquico (1.0, 1.1, 1.2)
     - DESCRIPCIÓN/ACTIVIDAD/DOCUMENTO/PLANO: Nombre del entregable
     - CANTIDAD: Número de unidades del entregable
     - CÓDIGOS PROFESIONALES: JP, IA, IB, IC, PA, PB, CD, CP, etc.
     - TOTAL HH: Suma de horas
   • VALORES: Números = Horas-hombre requeridas de cada rol para ese entregable
   • EJEMPLO: "ESTACIÓN DE BOMBEO" necesita 6 HH de JP + 10 HH de IB + 24 HH de IC
   • KEYWORDS: "HH", "horas", "dotación", "actividades", "entregables"

2. tarifas_profesionales:
   • OBJETIVO: Definir costo horario de cada tipo de profesional
   • COLUMNAS: Rol/Cargo, Tarifa/Rate, Moneda
   • VALORES: Precio por hora ($/hora, UF/hora)
   • KEYWORDS: "tarifa", "rate", "honorarios", "precio"

3. gastos_reembolsables:
   • OBJETIVO: Listar gastos operacionales
   • COLUMNAS: Descripción, Cantidad, Precio unitario, Total
   • VALORES: Montos de gastos (viajes, materiales)
   • KEYWORDS: "gasto", "viático", "pasaje", "reembolso"

4. desconocido: No calza con ningún tipo conocido

Responde SOLO JSON (sin ```json ni explicaciones):
{{"type": "entregables_profesionales", "confidence": 0.95}}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            return result.get("type", "desconocido"), float(result.get("confidence", 0.5))
        
        except Exception as e:
            print(f"❌ Error en AI: {e}")
            return "desconocido", 0.0
    
    def find_header_row(self, csv_snippet: str) -> Dict:
        """
        Encuentra la fila de encabezados (puede ser múltiple)
        
        Returns:
            {
                "header_rows": [1, 2],  # Puede ser una o más filas
                "is_multi_row": True,
                "confidence": 0.9,
                "column_mapping": {
                    "item": 1,
                    "descripcion": 2,
                    "cantidad": 3,
                    "JP": 7,
                    "IA": 9
                }
            }
        """
        self.call_count += 1
        
        prompt = f"""Eres experto en tablas de ingeniería. Detecta el ENCABEZADO (header) de esta tabla.

CONTEXTO: Las tablas de entregables vs profesionales tienen headers en 1 o 2 filas:
• Fila 1: ÍTEM, ACTIVIDAD/DOCUMENTO, CANTIDAD, "HH POR CATEGORÍA", TOTAL HH
• Fila 2: Códigos de profesionales (DC, PL, GL, JP, JD, IA, IB, PA, PB, CP, CD, ABIM)

PRIMERAS FILAS:
{csv_snippet[:3000]}

=== CÓDIGOS DE PROFESIONALES COMUNES ===
JP/JD: Jefes proyecto/disciplina
IA/IB/IC: Ingenieros senior/semi/junior
PA/PB/PC: Proyectistas senior/semi/junior
CP/CD: Control proyecto/documentos
DC/PL/GL: Variantes de control
ESP: Especialista
ABIM: Abogado/Asesor
CN: Coordinador

TAREA:
1. Identifica QUÉ FILA(S) contienen los encabezados (índice 0-based)
2. Detecta si es multi-línea (header en 2 filas)
3. Crea mapeo: nombre_columna → índice_columna

Responde SOLO JSON (sin ```json):
{{
    "header_rows": [1, 2],
    "is_multi_row": true,
    "confidence": 0.95,
    "column_mapping": {{
        "item": 1,
        "descripcion": 2,
        "cantidad": 3,
        "DC": 3,
        "PL": 4,
        "JP": 6,
        "IA": 9,
        "total_hh": 15
    }}
}}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            return {
                "header_rows": result.get("header_rows", []),
                "is_multi_row": result.get("is_multi_row", False),
                "confidence": float(result.get("confidence", 0.5)),
                "column_mapping": result.get("column_mapping", {})
            }
        
        except Exception as e:
            print(f"❌ Error buscando headers: {e}")
            return {
                "header_rows": [],
                "is_multi_row": False,
                "confidence": 0.0,
                "column_mapping": {}
            }
    
    def normalize_role(self, raw_role: str) -> Tuple[str, float]:
        """
        Normaliza nombre de rol a código estándar
        
        Returns:
            (role_code, confidence)
        """
        self.call_count += 1
        
        prompt = f"""Normaliza este rol a código estándar.

TEXTO: "{raw_role}"

CÓDIGOS VÁLIDOS:
JP=Jefe Proyecto, JD=Jefe Disciplina, CN=Coordinador, ESP=Especialista
IA/IB/IC=Ingenieros A/B/C, PA/PB/PC=Proyectistas A/B/C
DA/DB=Dibujantes, CD=Control Docs, CP=Control Proyecto
CA/CB=Calculistas, GP=Gerente, DI=Director, SI=Supervisor

Ejemplos:
"Jefe Proyecto" -> JP
"Ingeniero Senior" -> IA
"Proyectista Jr" -> PC

Responde SOLO JSON:
{{"code": "JP", "confidence": 0.95}}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50
            )
            
            result = json.loads(response.choices[0].message.content.strip())
            return result.get("code", "UNKNOWN").upper(), float(result.get("confidence", 0.5))
        
        except Exception as e:
            print(f"❌ Error normalizando rol: {e}")
            return "UNKNOWN", 0.0
    
    def analyze_deliverable_description(self, description: str) -> Dict:
        """
        Analiza la descripción de un entregable para extraer:
        - Disciplina(s) involucradas
        - Etapa del proyecto
        - Tipo de profesionales requeridos
        
        Returns:
            {
                "disciplinas": ["Piping", "Mecánica"],
                "etapa": "Ingeniería Básica",
                "profesionales_sugeridos": {
                    "IA": "Ingeniero especialista en piping",
                    "PA": "Proyectista para modelado 3D"
                },
                "confidence": 0.85
            }
        """
        self.call_count += 1
        
        prompt = f"""Eres experto en PROYECTOS DE INGENIERÍA INDUSTRIAL Y MINERA.

Analiza esta descripción de un entregable/actividad:

"{description}"

=== CONTEXTO ===
Esto viene de una tabla de planificación de horas-hombre (HH).
Debes identificar QUÉ DISCIPLINAS están involucradas y QUÉ PROFESIONALES se necesitan.

=== DISCIPLINAS COMUNES ===
• Mecánica: Equipos rotativos, estaciones de bombeo, estructuras metálicas, ventiladores
• Piping: Tuberías, cañerías, válvulas, instrumentación de línea, isométricos
• Eléctrica: Iluminación, tableros, motores, potencia, media tensión
• Instrumentación & Control: Sensores, PLCs, SCADA, automatización, lazos de control
• Civil: Fundaciones, movimiento tierras, pavimentos, estructuras hormigón
• Proceso: Diagramas flujo (PFD/P&ID), balances masa/energía, simulación
• Arquitectura: Layouts, distribución espacios, edificaciones
• HVAC: Climatización, ventilación
• General: Actividades transversales (NO específicas de disciplina)

=== TIPOS DE ENTREGABLES ===
• Plano: Dibujos técnicos, layouts, esquemas
• Documento: Especificaciones, memorias cálculo, procedimientos
• Modelo: Modelos 3D, BIM, CAD
• Informe: Reportes técnicos, estudios, análisis
• Cálculo: Hojas de cálculo, análisis ingenieriles
• Actividad: Reuniones, coordinación, control, revisiones

=== ETAPAS PROYECTO ===
• Conceptual: Estudios preliminares, factibilidad
• Básica: Ingeniería básica, diseño general
• Detalle: Ingeniería detalle, planos para construcción
• Construcción: Supervisión, as-built
• Puesta en marcha: Comisionamiento, pruebas

=== ROLES Y SUS FUNCIONES ===
• JP/JD: Jefe proyecto/disciplina → Liderazgo, coordinación estratégica
• IA: Ingeniero senior → Diseños complejos, cálculos avanzados, especificaciones
• IB: Ingeniero semi-senior → Diseños estándar, revisiones técnicas
• IC: Ingeniero junior → Apoyo técnico, cálculos básicos, revisiones
• PA: Proyectista senior → Planos complejos, modelado 3D avanzado
• PB: Proyectista semi-senior → Planos estándar, 2D/3D básico
• PC: Proyectista junior → Apoyo dibujo, detalles simples
• CP: Control proyecto → Planificación, cronogramas, seguimiento
• CD: Control documentos → Gestión documental, archivo, distribución
• ESP: Especialista → Expertise específico (ej: análisis sísmico, CFD)

EJEMPLOS:
1. "ESTACIÓN DE BOMBEO N°1" → 
   - Disciplinas: Mecánica (bombas), Piping (tuberías), Eléctrica (motores), Civil (fundaciones)
   - Roles: IA mecánico, IA piping, PA para planos, IC eléctrico

2. "Plano de cañerías sala bombas" →
   - Disciplinas: Piping
   - Roles: PA proyectista piping, IB revisor

3. "Reuniones técnicas semanales" →
   - General: Sí (no específico de disciplina)
   - Roles: JP coordinación

4. "Memoria de cálculo estructural" →
   - Disciplinas: Civil
   - Roles: IA civil estructural, IC apoyo cálculos

Responde SOLO JSON (sin ```json):
{{
    "disciplinas": ["Mecánica", "Piping"],
    "es_general": false,
    "tipo_entregable": "Plano",
    "etapa_proyecto": "Detalle",
    "roles_sugeridos": [
        {{"rol": "IA", "razon": "Diseño complejo de sistema de bombeo"}},
        {{"rol": "PA", "razon": "Planos de distribución de tuberías"}}
    ],
    "keywords": ["bombeo", "estación", "tuberías"],
    "confidence": 0.90
}}"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400
            )
            
            content = response.choices[0].message.content.strip()
            # Limpiar markdown si existe
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            result = json.loads(content)
            return {
                "disciplinas": result.get("disciplinas", ["General"]),
                "es_general": result.get("es_general", False),
                "tipo_entregable": result.get("tipo_entregable", ""),
                "etapa_proyecto": result.get("etapa_proyecto", ""),
                "roles_sugeridos": result.get("roles_sugeridos", []),
                "keywords": result.get("keywords", []),
                "confidence": float(result.get("confidence", 0.5))
            }
        
        except Exception as e:
            print(f"❌ Error analizando descripción: {e}")
            return {
                "disciplinas": ["General"],
                "es_general": True,
                "tipo_entregable": "",
                "etapa_proyecto": "",
                "roles_sugeridos": [],
                "keywords": [],
                "confidence": 0.0
            }
            return {
                "disciplinas": ["General"],
                "etapa": "",
                "profesionales_sugeridos": {},
                "confidence": 0.0
            }
    
    def extract_table_structure(self, csv_data: str, table_type: str) -> Dict:
        """
        Usa IA para extraer la estructura completa de una tabla compleja
        
        Args:
            csv_data: Datos de la hoja en formato CSV
            table_type: Tipo de tabla (entregables_profesionales, tarifas_profesionales, etc.)
        
        Returns:
            {
                "rows": [
                    {
                        "item": "1.1",
                        "descripcion": "Reuniones técnicas",
                        "cantidad": 5,
                        "JP": 10,
                        "IA": 20,
                        "disciplina": "General",
                        "etapa": "Ingeniería Básica"
                    }
                ],
                "confidence": 0.9
            }
        """
        self.call_count += 1
        
        if table_type == "entregables_profesionales":
            prompt = f"""Eres experto en análisis de tablas de proyectos de INGENIERÍA.

Extrae TODOS los entregables/actividades de esta tabla Excel:

DATOS:
{csv_data[:5000]}

=== CONTEXTO CRÍTICO ===
Esta es una matriz de entregables vs horas-hombre (HH) por profesional.

ESTRUCTURA TÍPICA:
- Encabezado 1: ÍTEM | ACTIVIDAD/DOCUMENTO | CANTIDAD | (columnas de profesionales) | TOTAL HH
- Encabezado 2 (opcional): Sub-headers con códigos de profesionales (JP, IA, IB, PA, CD, etc.)
- Datos: Filas con entregables y HH requeridas por cada profesional

CÓDIGOS DE PROFESIONALES COMUNES:
- JP/JD: Jefe Proyecto/Disciplina
- IA/IB/IC: Ingeniero senior/semi/junior
- PA/PB/PC: Proyectista senior/semi/junior
- CP/CD: Control proyecto/documentos
- ESP: Especialista

⚠️ IMPORTANTE - ROLES CON DISCIPLINA:
Si un header dice "Jefe de Ingeniería de Piping" o "Ingeniero Mecánico Senior":
1. Identifica el ROL base: Jefe=JP/JD, Ingeniero=IA/IB/IC
2. Identifica la DISCIPLINA: Piping, Mecánica, Eléctrica, Civil, etc.
3. Las HH de esa columna pertenecen a esa disciplina

Ejemplos:
- "Jefe Ingeniería Piping" → rol: JD, disciplina_col: Piping
- "Ingeniero Senior Mecánica" → rol: IA, disciplina_col: Mecánica
- "Proyectista Eléctrico" → rol: PA/PB, disciplina_col: Eléctrica
- "JP" solo → rol: JP, disciplina_col: null (general)

DISCIPLINAS POSIBLES:
Piping, Mecánica/Mechanical, Eléctrica/Electrical, Civil, Estructuras/Structures, 
Instrumentación/I&C, Proceso/Process, HVAC, Arquitectura

ANÁLISIS DE DESCRIPCIONES:
Para cada entregable, analiza su descripción e infiere:
- disciplinas: ["Piping", "Mecánica"] si menciona bombas, tuberías, etc.
- es_general: true si es reunión, control, coordinación (no específico)
- tipo: Plano, Documento, Modelo, Informe, Cálculo, Actividad

INSTRUCCIONES:
1. Detecta headers (1 o 2 filas)
2. Para CADA columna de profesional, extrae:
   - rol_base (JP, IA, etc.)
   - disciplina_col (si se menciona en el header)
3. Para CADA fila de datos:
   - item/código
   - descripcion
   - cantidad
   - HH por cada rol encontrado
   - Analiza descripción para inferir disciplinas del entregable
4. Ignora totales/subtotales
5. Máximo 50 filas

Responde SOLO JSON (sin ```json):
{{
    "columns_detected": [
        {{"col_idx": 3, "header": "JP", "rol": "JP", "disciplina": null}},
        {{"col_idx": 7, "header": "Jefe Ing. Piping", "rol": "JD", "disciplina": "Piping"}},
        {{"col_idx": 9, "header": "IA Mecánica", "rol": "IA", "disciplina": "Mecánica"}}
    ],
    "rows": [
        {{
            "item": "1.1",
            "descripcion": "Estación de bombeo",
            "cantidad": 1,
            "horas_por_rol": {{
                "JP": 10,
                "JD_Piping": 20,
                "IA_Mecanica": 40
            }},
            "disciplinas_detectadas": ["Piping", "Mecánica"],
            "es_general": false,
            "tipo": "Actividad"
        }}
    ],
    "confidence": 0.95
}}"""
        
        elif table_type == "tarifas_profesionales":
            prompt = f"""Extrae las tarifas de profesionales de esta tabla.

DATOS:
{csv_data[:3000]}

INSTRUCCIONES:
1. Identifica columnas: rol/cargo, tarifa/precio, moneda
2. Extrae cada profesional con su tarifa
3. Normaliza roles a códigos (JP, IA, IB, PA, etc.)

Responde SOLO JSON:
{{
    "rows": [
        {{"rol": "JP", "tarifa": 85000, "moneda": "CLP"}}
    ],
    "confidence": 0.95
}}"""
        
        else:
            return {"rows": [], "confidence": 0.0}
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000
            )
            
            content = response.choices[0].message.content.strip()
            # Limpiar markdown si existe
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            
            result = json.loads(content)
            return {
                "columns_detected": result.get("columns_detected", []),
                "rows": result.get("rows", []),
                "confidence": float(result.get("confidence", 0.5))
            }
        
        except Exception as e:
            print(f"❌ Error extrayendo estructura: {e}")
            return {"columns_detected": [], "rows": [], "confidence": 0.0}
    
    def get_stats(self) -> Dict:
        """Estadísticas de uso"""
        return {
            "total_calls": self.call_count,
            "model": self.model
        }
