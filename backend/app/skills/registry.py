"""SkillRegistry — patrón Claude Code Skills sobre Azure OpenAI tool calling.

Progressive disclosure:
  Nivel 1 — `catalog()` devuelve `name + description` para el system prompt (pocos tokens).
  Nivel 2 — `load(name)` devuelve el SKILL.md completo (tool call `load_skill`).
  Nivel 3 — recursos asociados (scripts/, references/, assets/) — pendiente, no usado hoy.

Cada skill vive en `backend/app/skills/<name>/SKILL.md` con frontmatter YAML:

    ---
    name: armar_propuesta
    description: ...
    allowed-tools: search_master, search_rag, ...
    ---
    # Markdown con el playbook
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None


class SkillRegistry:
    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or Path(__file__).resolve().parent
        self.skills: dict[str, Skill] = {}
        self._reload()

    def _reload(self) -> None:
        self.skills.clear()
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            md = skill_dir / "SKILL.md"
            if not md.exists():
                continue
            try:
                self.skills[skill_dir.name] = self._parse(md)
            except Exception:
                continue

    def _parse(self, path: Path) -> Skill:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._split_frontmatter(text)
        meta = self._parse_frontmatter(frontmatter)
        return Skill(
            name=meta.get("name") or path.parent.name,
            description=meta.get("description", "").strip(),
            allowed_tools=[t.strip() for t in (meta.get("allowed-tools") or "").split(",") if t.strip()],
            body=body.strip(),
            path=path,
        )

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[str, str]:
        if not text.startswith("---"):
            return "", text
        _, _, rest = text.partition("---")
        fm, _, body = rest.partition("---")
        return fm, body

    @staticmethod
    def _parse_frontmatter(fm: str) -> dict:
        meta: dict[str, str] = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        return meta

    # ---- API pública ----

    def list_skills(self) -> list[Skill]:
        return list(self.skills.values())

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def catalog(self) -> str:
        """String formateado para inyectar en el system prompt (nivel 1).

        Mínimo: cada línea es `- nombre: descripción`. Bajo en tokens.
        """
        lines = []
        for s in self.skills.values():
            desc = re.sub(r"\s+", " ", s.description)[:240]
            lines.append(f"- **{s.name}**: {desc}")
        return "\n".join(lines)

    def load(self, name: str) -> dict:
        """Devuelve el SKILL.md completo (nivel 2) para inyectar como tool result.

        El agente la invoca vía la tool `load_skill(name)`.
        """
        skill = self.skills.get(name)
        if not skill:
            return {"error": f"skill '{name}' no existe", "available": list(self.skills.keys())}
        return {
            "name": skill.name,
            "description": skill.description,
            "allowed_tools": skill.allowed_tools,
            "instructions": skill.body,
        }
