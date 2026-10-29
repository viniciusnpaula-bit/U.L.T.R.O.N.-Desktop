"""Skills do ULTRON: procedimentos em dados/skills/<slug>/SKILL.md.

Módulo folha: não importa cerebro, ferramentas nem seguranca. Estado é derivado
do último uso, então nada aqui precisa rodar para o índice estar correto.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import config

BASE = Path(__file__).resolve().parent / "dados" / "skills"
PENDENTES = BASE / ".pendentes"
USO = BASE / ".uso.json"

_CACHE: dict[str, object] = {"chave": None, "ativos": [], "pendentes": []}
_USO_CACHE: dict[str, object] = {"chave": None, "dados": {}}


@dataclass(frozen=True)
class Skill:
    slug: str
    nome: str
    descricao: str
    quando: str
    criado_por: str
    criado_em: str
    corpo: str
    pendente: bool = False


def slugificar(nome: str) -> str:
    """Nome livre -> slug seguro. Nunca devolve caminho: só [a-z0-9-]."""
    base = unicodedata.normalize("NFKD", nome or "")
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:40]
    return base or "skill"


def _limite_corpo() -> int:
    return int(getattr(config, "SKILLS_CORPO_MAX", 2000))


def _ler(caminho: Path, pendente: bool) -> Skill | None:
    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError:
        return None
    if not texto.lstrip().startswith("---"):
        return None
    partes = texto.split("---", 2)
    if len(partes) < 3:
        return None
    meta: dict[str, str] = {}
    for linha in partes[1].splitlines():
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        meta[chave.strip().lower()] = valor.split("#")[0].strip()
    if not all(meta.get(campo) for campo in ("nome", "descricao", "quando")):
        return None
    return Skill(
        slug=caminho.parent.name,
        nome=meta["nome"],
        descricao=meta["descricao"],
        quando=meta["quando"],
        criado_por=meta.get("criado_por", "usuario"),
        criado_em=meta.get("criado_em", ""),
        corpo=partes[2].strip()[:_limite_corpo()],
        pendente=pendente,
    )


def _varrer(pasta: Path, pendente: bool) -> list[Skill]:
    if not pasta.is_dir():
        return []
    achadas = []
    for caminho in sorted(pasta.glob("*/SKILL.md")):
        skill = _ler(caminho, pendente)
        if skill:
            achadas.append(skill)
    return achadas


def _assinatura() -> tuple:
    itens = []
    for pasta in (BASE, PENDENTES):
        if pasta.is_dir():
            for caminho in sorted(pasta.glob("*/SKILL.md")):
                try:
                    itens.append((str(caminho), caminho.stat().st_mtime_ns))
                except OSError:
                    pass
    return (str(BASE), tuple(itens))


def _carregar():
    chave = _assinatura()
    if _CACHE["chave"] != chave:
        _CACHE["chave"] = chave
        _CACHE["ativos"] = _varrer(BASE, pendente=False)
        _CACHE["pendentes"] = _varrer(PENDENTES, pendente=True)
    return _CACHE["ativos"], _CACHE["pendentes"]


def invalidar() -> None:
    _CACHE["chave"] = None
    _USO_CACHE["chave"] = None


def listar() -> list[Skill]:
    return list(_carregar()[0])


def pendentes() -> list[Skill]:
    return list(_carregar()[1])


def _uso() -> dict[str, str]:
    """Lê .uso.json no máximo uma vez por versão do arquivo (o índice consulta
    o uso de cada skill, e não pode virar N leituras por resposta)."""
    try:
        info = USO.stat()
        chave = (info.st_mtime_ns, info.st_size)
    except OSError:
        return {}
    if _USO_CACHE["chave"] != chave:
        try:
            dados = json.loads(USO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        _USO_CACHE["chave"] = chave
        _USO_CACHE["dados"] = dados if isinstance(dados, dict) else {}
    return _USO_CACHE["dados"]


def _data(texto: str) -> date | None:
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def estado(skill: Skill, agora: date | None = None) -> str:
    hoje = agora or date.today()
    referencia = _data(_uso().get(skill.slug, "")) or _data(skill.criado_em) or hoje
    dias = (hoje - referencia).days
    if dias >= int(getattr(config, "SKILLS_ARQUIVAR_DIAS", 90)):
        return "arquivado"
    if dias >= int(getattr(config, "SKILLS_STALE_DIAS", 30)):
        return "obsoleto"
    return "ativo"


def indice() -> str:
    if not getattr(config, "SKILLS_ATIVO", True):
        return ""
    limite = int(getattr(config, "SKILLS_MAX_INDICE", 15))
    linhas = []
    for skill in listar():
        if estado(skill) != "ativo":
            continue
        linha = f"- {skill.nome}: {' '.join(skill.quando.split())}"
        linhas.append(linha if len(linha) <= 90 else linha[:89] + "…")
        if len(linhas) >= limite:
            break
    return "\n".join(linhas)


def corpo(slug: str) -> str:
    """Só skills aprovadas: pendente é inerte e o agente não pode lê-la."""
    for skill in listar():
        if skill.slug == slug or skill.nome.lower() == slug.lower():
            return skill.corpo
    return ""
