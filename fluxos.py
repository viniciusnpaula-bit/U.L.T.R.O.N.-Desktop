"""Fluxos nomeados: sequências de passos que param na primeira falha.

Cada passo usa uma ferramenta já registrada, pelo portão `ferramentas.executar`
(sem caminho alternativo de execução). Se um passo falhar, o fluxo PARA e informa
qual etapa falhou — as seguintes não são executadas, como manda a regra do projeto.

Qualquer LLM não recebe a lista de passos como instrução livre: o fluxo é definido
no código, com nome, ferramentas e ordem fixos.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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


def listar() -> list[dict]:
    return [{"id": f.id, "titulo": f.titulo, "descricao": f.descricao,
             "etapas": [p.rotulo for p in f.passos]} for f in FLUXOS.values()]


def obter(fluxo_id: str) -> Fluxo | None:
    return FLUXOS.get(str(fluxo_id or "").strip())


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
