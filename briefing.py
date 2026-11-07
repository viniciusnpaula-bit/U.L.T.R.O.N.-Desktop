"""Briefing matinal: junta clima, notícias, agenda e lembretes em um texto curto."""
from __future__ import annotations

import datetime

import config


def hora_configurada() -> tuple[int, int]:
    texto = str(getattr(config, "BRIEFING_HORA", "08:00") or "08:00")
    try:
        hora, minuto = (int(parte) for parte in texto.split(":")[:2])
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return hora, minuto
    except (TypeError, ValueError):
        pass
    return 8, 0


def devido(agora=None, ultimo=None) -> bool:
    """True quando já passou da hora configurada e o briefing ainda não saiu hoje."""
    if not getattr(config, "BRIEFING_ATIVO", False):
        return False
    agora = agora or datetime.datetime.now()
    hora, minuto = hora_configurada()
    if agora < agora.replace(hour=hora, minute=minuto, second=0, microsecond=0):
        return False
    return str(ultimo or "") != agora.date().isoformat()


def _limpar(texto: str) -> str:
    linhas = []
    for linha in str(texto or "").splitlines():
        if linha.startswith(("[DADOS EXTERNOS", "[IMAGEM_DESTAQUE")):
            continue
        linhas.append(linha)
    return "\n".join(linhas).strip()


def compor(agora=None, cidade=None, executar_ferramenta=None):
    """Texto do briefing. Nunca levanta: seção que falhar é só omitida."""
    agora = agora or datetime.datetime.now()
    cidade = cidade or getattr(config, "CIDADE", "São Paulo")
    if executar_ferramenta is None:
        import ferramentas
        executar_ferramenta = ferramentas.executar

    def chamar(nome, argumentos):
        try:
            return _limpar(executar_ferramenta(nome, argumentos, lambda _pedido: False, "briefing"))
        except Exception:
            return ""

    partes = [f"Bom dia, {config.NOME}."]
    clima = chamar("clima", {"cidade": cidade})
    if clima:
        partes.append(f"Clima:\n{clima}")
    noticias = chamar("noticias", {"tema": "geral"})
    if noticias:
        partes.append(f"Notícias:\n{noticias}")

    try:
        import memoria
        eventos = memoria.eventos_do_dia(agora.timestamp())
        if eventos:
            linhas = [f"- {item['hora_local']}: {item['texto']}" for item in eventos[:8]]
            partes.append("Agenda de hoje:\n" + "\n".join(linhas))
        lembretes = memoria.lembretes_pendentes()
        if lembretes:
            linhas = [f"- {datetime.datetime.fromtimestamp(due).strftime('%d/%m %H:%M')}: {texto}"
                      for due, texto in lembretes[:8]]
            partes.append("Lembretes:\n" + "\n".join(linhas))
    except Exception:
        pass
    return "\n\n".join(parte for parte in partes if parte)
