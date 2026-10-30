"""Skills do ULTRON: procedimentos em dados/skills/<slug>/SKILL.md.

Módulo folha: não importa cerebro, ferramentas nem seguranca. Estado é derivado
do último uso, então nada aqui precisa rodar para o índice estar correto.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
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
        mtime = caminho.stat().st_mtime
    except (OSError, UnicodeDecodeError):
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
        criado_em=meta.get("criado_em") or datetime.fromtimestamp(mtime).date().isoformat(),
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
        ativos = _varrer(BASE, pendente=False)
        pend = _varrer(PENDENTES, pendente=True)
        _CACHE["ativos"] = ativos
        _CACHE["pendentes"] = pend
        _CACHE["chave"] = chave  # por último: ninguém vê chave nova com listas velhas
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
    if limite <= 0:
        return ""
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
    if not getattr(config, "SKILLS_ATIVO", True):
        return ""
    for skill in listar():
        if skill.slug == slug or skill.nome.lower() == slug.lower():
            return skill.corpo
    return ""


def _pasta(base: Path, slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", slug or ""):
        raise ValueError("nome de skill inválido")
    return base / slug


def _escrever(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=caminho.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
        os.replace(tmp, caminho)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def criar(nome, descricao, quando, corpo, criado_por="agente") -> str:
    """Grava uma pendente. O agente cria; só o humano aprova."""
    slug = slugificar(nome)
    for existente in listar() + pendentes():
        if existente.slug == slug:
            return slug
    maximo = int(getattr(config, "SKILLS_PENDENTES_MAX", 3))
    if len(pendentes()) >= maximo:
        raise ValueError("fila de skills cheia: aprove ou descarte antes de criar outra")
    texto = (
        "---\n"
        f"nome: {' '.join(str(nome).split())[:80]}\n"
        f"descricao: {' '.join(str(descricao).split())[:160]}\n"
        f"quando: {' '.join(str(quando).split())[:160]}\n"
        f"criado_por: {' '.join(str(criado_por).split())}\n"
        f"criado_em: {date.today().isoformat()}\n"
        "---\n\n"
        f"{str(corpo).strip()[:_limite_corpo()]}\n"
    )
    _escrever(_pasta(PENDENTES, slug) / "SKILL.md", texto)
    invalidar()
    return slug


def aprovar(slug: str) -> str:
    origem = _pasta(PENDENTES, slug)
    if not (origem / "SKILL.md").is_file():
        raise ValueError(f"skill pendente não encontrada: {slug}")
    destino = _pasta(BASE, slug)
    if destino.exists():
        raise ValueError(f"já existe skill com esse nome: {slug}")
    maximo = int(getattr(config, "SKILLS_MAX_TOTAL", 100))
    if len(listar()) >= maximo:
        raise ValueError(f"limite de {maximo} skills ativas: apague alguma antes de aprovar")
    shutil.move(str(origem), str(destino))
    invalidar()
    return slug


def descartar(slug: str) -> bool:
    """True se removeu uma pendente; False se o slug não era pendente."""
    alvo = _pasta(PENDENTES, slug)
    if not alvo.is_dir():
        return False
    shutil.rmtree(alvo)
    invalidar()
    return True


def marcar_uso(slug: str) -> None:
    dados = _uso()
    dados[slug] = date.today().isoformat()
    _escrever(USO, json.dumps(dados, ensure_ascii=False))
    invalidar()  # cache de _uso() é por (mtime, size): não depender do filesystem


def curar(agora=None) -> dict:
    """Só relata: não move nem apaga nada."""
    hoje = agora or date.today()
    ativos = [s for s in listar() if estado(s, hoje) == "ativo"]
    avisos = []
    dias = int(getattr(config, "SKILLS_PENDENTE_DIAS", 7))
    for skill in pendentes():
        criada = _data(skill.criado_em)
        if criada and (hoje - criada).days > dias:
            avisos.append(f"skill pendente há {(hoje - criada).days} dias: {skill.slug}")
    return {
        "ativos": len(ativos),
        "obsoletos": len([s for s in listar() if estado(s, hoje) == "obsoleto"]),
        "arquivados": len([s for s in listar() if estado(s, hoje) == "arquivado"]),
        "pendentes": len(pendentes()),
        "avisos": avisos,
    }
