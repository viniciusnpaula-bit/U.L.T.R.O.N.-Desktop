"""Fluxos nomeados: sequências de passos que param na primeira falha.

Cada passo usa uma ferramenta já registrada, pelo portão `ferramentas.executar`
(sem caminho alternativo de execução). Se um passo falhar, o fluxo PARA e informa
qual etapa falhou — as seguintes não são executadas, como manda a regra do projeto.

Fluxos fixos vivem no código. Fluxos criados pelo usuário ficam em
`dados/fluxos.json` e nunca podem substituir um fluxo fixo.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from config import BASE

ARQUIVO_USUARIO = BASE / "dados" / "fluxos.json"


@dataclass(frozen=True)
class Passo:
    rotulo: str          # o que aparece para o usuário
    ferramenta: str      # nome da ferramenta registrada
    argumentos: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Fluxo:
    id: str
    titulo: str
    descricao: str
    passos: tuple[Passo, ...]


FLUXOS: dict[str, Fluxo] = {
    "abrir.rocket": Fluxo(
        id="abrir.rocket",
        titulo="Abrir Rocket League",
        descricao="Abre somente o jogo.",
        passos=(Passo("abrir o Rocket League", "abrir_programa", {"nome": "Rocket League"}),),
    ),
    "modo_jogo": Fluxo(
        id="modo_jogo",
        titulo="Modo jogo",
        descricao="Abre o Rocket League, abre o Spotify e minimiza as janelas, nessa ordem.",
        passos=(
            Passo("abrir o Rocket League", "abrir_programa", {"nome": "Rocket League"}),
            Passo("abrir o Spotify", "abrir_programa", {"nome": "Spotify"}),
            Passo("minimizar as janelas", "minimizar_janelas", {}),
        ),
    ),
    "minimizar": Fluxo(
        id="minimizar",
        titulo="Minimizar tudo",
        descricao="Minimiza as janelas como ação separada.",
        passos=(Passo("minimizar as janelas", "minimizar_janelas", {}),),
    ),
}

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


def _ler_usuario() -> dict:
    try:
        dados = json.loads(ARQUIVO_USUARIO.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _salvar(dados: dict) -> None:
    ARQUIVO_USUARIO.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_USUARIO.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporario, ARQUIVO_USUARIO)


def _fluxo_de_dict(fluxo_id: str, dados: dict) -> Fluxo | None:
    try:
        passos = tuple(
            Passo(str(p.get("rotulo") or p["ferramenta"]), str(p["ferramenta"]),
                  dict(p.get("argumentos") or {}))
            for p in dados["passos"])
        if not passos:
            return None
        return Fluxo(fluxo_id, str(dados.get("titulo") or fluxo_id),
                     str(dados.get("descricao") or ""), passos)
    except (KeyError, TypeError, AttributeError):
        return None


def _usuario() -> dict[str, Fluxo]:
    saida = {}
    for fluxo_id, dados in _ler_usuario().items():
        if str(fluxo_id) in FLUXOS or not isinstance(dados, dict):
            continue
        fluxo = _fluxo_de_dict(str(fluxo_id), dados)
        if fluxo is not None:
            saida[fluxo.id] = fluxo
    return saida


def _validar(fluxo_id, titulo, descricao, passos) -> tuple[str, dict]:
    fluxo_id = str(fluxo_id or "").strip().lower()
    if not _ID.match(fluxo_id):
        raise ValueError("O id do fluxo deve ter letras minúsculas, números, ponto, hífen ou _ (até 40).")
    if fluxo_id in FLUXOS:
        raise ValueError(f"'{fluxo_id}' é um fluxo fixo e não pode ser substituído.")
    if not isinstance(passos, list) or not passos:
        raise ValueError("O fluxo precisa de pelo menos um passo.")
    if len(passos) > 12:
        raise ValueError("O fluxo aceita no máximo 12 passos.")
    import ferramentas      # tardio: evita ciclo na importação
    limpos = []
    for passo in passos:
        if not isinstance(passo, dict) or not isinstance(passo.get("ferramenta"), str):
            raise ValueError("Cada passo precisa de 'ferramenta' e, opcionalmente, 'rotulo' e 'argumentos'.")
        nome = passo["ferramenta"]
        if nome not in ferramentas.FERRAMENTAS:
            raise ValueError(f"Ferramenta desconhecida no fluxo: {nome}")
        argumentos = passo.get("argumentos") or {}
        if not isinstance(argumentos, dict):
            raise ValueError("'argumentos' de cada passo precisa ser um objeto.")
        limpos.append({"rotulo": str(passo.get("rotulo") or nome)[:120],
                       "ferramenta": nome, "argumentos": argumentos})
    return fluxo_id, {"titulo": str(titulo or fluxo_id)[:80],
                      "descricao": str(descricao or "")[:240], "passos": limpos}


def criar(fluxo_id, titulo, descricao, passos) -> Fluxo:
    fluxo_id, dados = _validar(fluxo_id, titulo, descricao, passos)
    usuario = _ler_usuario()
    usuario[fluxo_id] = dados
    _salvar(usuario)
    return obter(fluxo_id)


def remover(fluxo_id) -> bool:
    fluxo_id = str(fluxo_id or "").strip().lower()
    if fluxo_id in FLUXOS:
        raise ValueError("Fluxos fixos não podem ser removidos.")
    usuario = _ler_usuario()
    if fluxo_id not in usuario:
        return False
    del usuario[fluxo_id]
    _salvar(usuario)
    return True


def listar() -> list[dict]:
    todos = list(FLUXOS.values()) + list(_usuario().values())
    return [{"id": f.id, "titulo": f.titulo, "descricao": f.descricao,
             "etapas": [p.rotulo for p in f.passos]} for f in todos]


def obter(fluxo_id: str) -> Fluxo | None:
    fluxo_id = str(fluxo_id or "").strip()
    if fluxo_id in FLUXOS:
        return FLUXOS[fluxo_id]
    return _usuario().get(fluxo_id)


def executar(fluxo_id: str, executar_ferramenta, confirmar=None, origem="fluxo"):
    """Executa as etapas em ordem, SEMPRE pelo portão de ferramentas.

    Devolve {"ok", "etapas": [{rotulo, ok, resultado}], "falhou_em", "resumo"}.
    Nenhuma etapa seguinte roda depois de uma falha.
    """
    fluxo = obter(fluxo_id)
    if fluxo is None:
        return {"ok": False, "etapas": [], "falhou_em": None, "resumo": "Fluxo desconhecido."}
    etapas = []
    for passo in fluxo.passos:
        try:
            resultado = executar_ferramenta(passo.ferramenta, dict(passo.argumentos), confirmar, origem)
        except Exception as erro:      # falha de etapa: nada de continuar
            etapas.append({"rotulo": passo.rotulo, "ok": False,
                           "resultado": f"erro interno ({type(erro).__name__})"})
            return {"ok": False, "etapas": etapas, "falhou_em": passo.rotulo,
                    "resumo": f"Parei em “{passo.rotulo}”: falha interna."}
        texto = str(resultado or "")
        negado = texto.startswith("AÇÃO NEGADA") or "cancelad" in texto.lower()
        falhou = texto.startswith(("Erro ao executar", "Argumentos inválidos", "Ferramenta desconhecida",
                                   "Não encontrei", "não consegui", "Comando bloqueado"))
        etapas.append({"rotulo": passo.rotulo, "ok": not (negado or falhou), "resultado": texto[:300]})
        if negado or falhou:
            motivo = "negada pela segurança" if negado else texto[:120]
            return {"ok": False, "etapas": etapas, "falhou_em": passo.rotulo,
                    "resumo": f"Parei em “{passo.rotulo}”: {motivo}."}
    return {"ok": True, "etapas": etapas, "falhou_em": None,
            "resumo": f"{fluxo.titulo} concluído ({len(etapas)} etapa(s))."}
