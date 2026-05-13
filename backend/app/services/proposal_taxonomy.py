import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeLabel:
    code: str
    label: str
    category: str | None = None


NEGOTIATION_TYPES: dict[str, CodeLabel] = {
    "ND": CodeLabel("ND", "Negociacion Directa"),
    "LM": CodeLabel("LM", "Licitacion Multiple"),
    "AC": CodeLabel("AC", "Apoyo Contratos"),
    "LC": CodeLabel("LC", "Licitacion Contrato Abierto"),
    "NA": CodeLabel("N/A", "No Aplica"),
    "N/A": CodeLabel("N/A", "No Aplica"),
}

SERVICE_TYPES: dict[str, CodeLabel] = {
    "IP": CodeLabel("IP", "Ingenieria de Perfil", "Proyecto T: Perfil / Conceptual / Prefactibilidad"),
    "IC": CodeLabel("IC", "Ingenieria Conceptual", "Proyecto T: Perfil / Conceptual / Prefactibilidad"),
    "IB": CodeLabel("IB", "Ingenieria Basica", "Proyecto P: Basica / Detalle / Contraparte"),
    "ID": CodeLabel("ID", "Ingenieria de Detalle", "Proyecto P: Basica / Detalle / Contraparte"),
    "CO": CodeLabel("CO", "Ingenieria de Contraparte", "Proyecto P: Basica / Detalle / Contraparte"),
    "CC": CodeLabel("CC", "Comision de Confianza / Auditoria / Estudio / Diagnostico / Benchmarking / Bases", "Proyecto D"),
    "EP": CodeLabel("EP", "Ingenieria, Adquisicion y Construccion", "Proyecto P: EPC/EPCM"),
    "CM": CodeLabel("CM", "Administracion de Construccion", "Proyecto P: EPC/EPCM"),
    "C": CodeLabel("C", "Construccion", "Proyecto P: EPC/EPCM"),
    "AD": CodeLabel("AD", "Adquisiciones", "Proyecto P"),
    "CA": CodeLabel("CA", "Contratos Abiertos / Contrato Marco / Asesoria", "Proyecto F"),
    "IT": CodeLabel("IT", "Ingenieria de Terreno", "Proyecto S"),
    "AO": CodeLabel("AO", "Apoyo a Operaciones / Manuales / PEM", "Proyecto S"),
    "TP": CodeLabel("TP", "Transferencia de Profesionales", "Proyecto G"),
    "CT": CodeLabel("CT", "Capacitacion a Terceros", "Proyecto C"),
    "VD": CodeLabel("VD", "Venta de Dragas y Elementos Relacionados", "Proyecto Q"),
    "PR": CodeLabel("PR", "Precalificacion / Inscripcion / Registro"),
    "OS": CodeLabel("OS", "Otros Servicios"),
    "NA": CodeLabel("N/A", "No Aplica"),
    "N/A": CodeLabel("N/A", "No Aplica"),
}

SCOPE_TYPES: dict[str, CodeLabel] = {
    "NAC": CodeLabel("NAC", "Nacional"),
    "INT": CodeLabel("INT", "Internacional"),
}

STATUS_TYPES: dict[str, CodeLabel] = {
    "PDS": CodeLabel("PDS", "Por Definir Situacion", "indefinida"),
    "EP": CodeLabel("EP", "En Preparacion", "en_preparacion"),
    "NL": CodeLabel("NL", "Propuesta No Licitada", "no_licitada"),
    "DP": CodeLabel("DP", "Decision del Cliente Pendiente", "pendiente"),
    "PG": CodeLabel("PG", "Propuesta Ganada", "ganada"),
    "PP": CodeLabel("PP", "Propuesta Perdida", "perdida"),
    "PD": CodeLabel("PD", "Propuesta Declarada Desierta", "desierta"),
}

ENTITY_PATTERNS: dict[str, list[str]] = {
    "etapa_ingenieria": [
        "perfil",
        "conceptual",
        "prefactibilidad",
        "factibilidad",
        "basica",
        "detalle",
        "contraparte",
        "epcm",
        "construccion",
    ],
    "instalaciones_mineras": [
        "rajo abierto",
        "open pit",
        "fondo mina",
        "mina subterranea",
        "planta concentradora",
        "chancado",
        "molienda",
        "flotacion",
        "tranque",
        "deposito",
        "embalse",
        "botadero",
        "pila",
    ],
    "procesos_sistemas": [
        "dewatering",
        "desague",
        "drenaje",
        "bombeo",
        "impulsion",
        "conduccion",
        "recirculacion",
        "abatimiento",
        "tratamiento de aguas",
        "relaves",
        "transporte de relaves",
        "disposicion de relaves",
        "aguas recuperadas",
        "sulfatos",
    ],
    "disciplinas": [
        "civil",
        "hidraulica",
        "mecanica",
        "piping",
        "electrica",
        "instrumentacion",
        "control",
        "geotecnia",
        "procesos",
        "estructural",
        "costos",
        "planificacion",
    ],
    "componentes": [
        "bombas",
        "pozos",
        "piscinas",
        "estanques",
        "tuberias",
        "canales",
        "valvulas",
        "salas electricas",
        "subestacion",
        "linea electrica",
        "relaveducto",
        "acueducto",
    ],
    "artefactos_propuesta": [
        "alcance",
        "objetivo",
        "metodologia",
        "entregables",
        "exclusiones",
        "supuestos",
        "cronograma",
        "plazo",
        "organigrama",
        "horas hombre",
        "hh",
        "tarifa",
        "estimacion",
    ],
}


def enrich_metadata(metadata: dict) -> dict:
    enriched = dict(metadata)
    text = " ".join(str(enriched.get(key, "")) for key in ["titulo", "cliente", "cliente_final", "tipo_servicio", "estado"])
    enriched["estado_info"] = code_info(enriched.get("estado"), STATUS_TYPES)
    enriched["tipo_servicio_info"] = split_code_info(enriched.get("tipo_servicio"), SERVICE_TYPES)
    enriched["tipo_negociacion_info"] = code_info(enriched.get("tipo_negociacion"), NEGOTIATION_TYPES)
    enriched["ambito_info"] = code_info(enriched.get("ambito"), SCOPE_TYPES)
    enriched["estado_categoria"] = status_category(enriched.get("estado"))
    enriched["propuesta_ganada"] = enriched["estado_categoria"] == "ganada"
    enriched["propuesta_perdida"] = enriched["estado_categoria"] == "perdida"
    enriched["entidades_taxonomia"] = extract_entities(text)
    enriched["metadata_version"] = "proposal_taxonomy_v1"
    return enriched


def code_info(value: object, catalog: dict[str, CodeLabel]) -> dict | None:
    code = normalize_code(value)
    if not code:
        return None
    item = catalog.get(code)
    if not item:
        return {"code": code, "label": None, "category": None}
    return {"code": item.code, "label": item.label, "category": item.category}


def split_code_info(value: object, catalog: dict[str, CodeLabel]) -> list[dict]:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "no data":
        return []
    codes = [normalize_code(part) for part in re.split(r"[/,;+\s]+", raw) if normalize_code(part)]
    return [code_info(code, catalog) or {"code": code, "label": None, "category": None} for code in codes]


def extract_entities(text: str) -> dict[str, list[str]]:
    norm = normalize_text(text)
    entities: dict[str, list[str]] = {}
    for group, terms in ENTITY_PATTERNS.items():
        found = [term for term in terms if normalize_text(term) in norm]
        if found:
            entities[group] = found
    return entities


def status_category(value: object) -> str:
    code = normalize_code(value)
    if code == "PG":
        return "ganada"
    if code == "PP":
        return "perdida"
    if code == "PD":
        return "desierta"
    if code in {"DP", "PDS"}:
        return "pendiente"
    if code == "EP":
        return "en_preparacion"
    if code == "NL":
        return "no_licitada"
    return "desconocida"


def normalize_code(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text == "NO DATA":
        return ""
    if text in {"N A", "NA", "N.A."}:
        return "N/A"
    return text


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text)
