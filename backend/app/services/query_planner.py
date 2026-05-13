import unicodedata


CONCEPT_SYNONYMS = {
    "open_pit": {
        "triggers": ["open pit", "openpit", "pit", "rajo abierto", "rajo", "mina cielo abierto", "cielo abierto"],
        "terms": ["open pit", "rajo abierto", "rajo", "cielo abierto", "mina", "pit"],
    },
    "dewatering": {
        "triggers": ["dewatering", "desague", "desaguar", "drenaje", "abatimiento", "agua mina", "aguas mina"],
        "terms": ["dewatering", "desague", "desaguar", "drenaje", "abatimiento", "agua", "aguas"],
    },
    "pumping": {
        "triggers": ["bombeo", "bomba", "bombas", "impulsion", "impulsión", "sistema de bombeo", "estacion de bombeo"],
        "terms": ["bombeo", "bomba", "bombas", "impulsion", "impulsión", "piping", "tuberia", "tuberías"],
    },
    "tailings": {
        "triggers": ["relaves", "relave", "tailings", "tranque", "deposito de relaves", "depósito de relaves", "relaveducto", "rejeito", "rejeitoduto"],
        "terms": ["relaves", "relave", "tailings", "tranque", "deposito", "depósito", "depositacion", "depositación", "relaveducto", "rejeito", "rejeitoduto"],
    },
    "tailings_disposal": {
        "triggers": ["disposicion", "disposición", "disposicion alternativa", "disposición alternativa", "alternativa de relaves", "depositacion alternativa", "depósito alternativo"],
        "terms": ["disposicion", "disposición", "alternativa", "alternativas", "depositacion", "depositación", "deposito", "depósito", "trade off", "trade-off"],
    },
    "feasibility": {
        "triggers": ["factibilidad", "prefactibilidad", "perfil", "conceptual", "trade off", "trade-off", "alternativas"],
        "terms": ["factibilidad", "prefactibilidad", "perfil", "conceptual", "alternativas", "trade off", "trade-off"],
    },
    "flotation": {
        "triggers": ["flotacion", "flotación", "celda", "celdas", "celdas de flotacion", "celdas de flotación"],
        "terms": ["flotacion", "flotación", "celda", "celdas", "columnares", "scavenger"],
    },
    "maintenance": {
        "triggers": ["mantenimiento", "mantencion", "mantención", "inspeccion", "inspección"],
        "terms": ["mantenimiento", "mantencion", "mantención", "inspeccion", "inspección"],
    },
}


class QueryPlanner:
    def expand(self, question: str, llm_plan: dict) -> dict:
        llm_keywords = [str(item).strip() for item in llm_plan.get("keywords", []) if str(item).strip()]
        normalized_question = self._norm(" ".join([question, *llm_keywords]))
        concepts = []
        expanded_terms = []

        for name, config in CONCEPT_SYNONYMS.items():
            if any(self._norm(trigger) in normalized_question for trigger in config["triggers"]):
                concepts.append(name)
                expanded_terms.extend(config["terms"])

        for keyword in llm_keywords:
            expanded_terms.append(keyword)
            expanded_terms.extend(self._split_phrase(keyword))

        expanded_terms = self._dedupe(expanded_terms)
        alternatives = self._alternatives(concepts, expanded_terms)
        return {
            "concepts": concepts,
            "keywords": expanded_terms[:28],
            "alternatives": alternatives,
        }

    def _alternatives(self, concepts: list[str], expanded_terms: list[str]) -> list[str]:
        alternatives = []
        if {"open_pit", "dewatering", "pumping"}.issubset(set(concepts)):
            alternatives.extend(
                [
                    "sistema dewatering mina",
                    "dewatering mina",
                    "open pit dewatering pumping",
                    "rajo abierto desague bombeo",
                    "drenaje rajo abierto bombas",
                    "sistema bombeo aguas mina",
                    "abatimiento agua mina impulsion",
                ]
            )
        if "tailings" in concepts:
            alternatives.extend(
                [
                    "disposicion alternativa relaves",
                    "disposición alternativa relaves",
                    "factibilidad disposicion relaves",
                    "factibilidad tranque relaves",
                    "prefactibilidad transporte relaves aguas recuperadas",
                    "deposito relaves alternativas",
                    "depositacion relaves",
                    "relaveducto transporte relaves",
                    "rejeitoduto relaves",
                    "tranque relaves drenaje",
                ]
            )
        if {"flotation", "maintenance"}.issubset(set(concepts)):
            alternatives.extend(
                [
                    "mantenimiento celdas flotacion",
                    "celdas flotacion mantenimiento",
                    "mejoramiento atriles mantenimiento",
                    "reemplazo celdas columnas scavenger",
                ]
            )
        if not alternatives:
            alternatives = [" ".join(expanded_terms[:6])]
            alternatives.extend(expanded_terms[:8])
        return self._dedupe(alternatives)[:10]

    def _split_phrase(self, value: str) -> list[str]:
        return [part for part in self._norm(value).split() if len(part) >= 3]

    def _dedupe(self, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            normalized = self._norm(value).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value.strip())
        return result

    def _norm(self, value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value).lower())
        return "".join(ch for ch in text if not unicodedata.combining(ch))
