"""Autoconhecimento em runtime: o que o ULTRON é, onde roda e o que pode fazer.

O bloco é montado a partir do sistema vivo — nome/perfil, versão do pacote, SO,
ferramentas realmente registradas, voz e limites — e guardado uma vez por
processo. Nada de WMI ou PowerShell aqui: o system prompt é montado a cada
resposta e precisa ser barato.

O que é dinâmico (nome, versão, ferramentas) nunca é inventado: se a leitura
falhar, o bloco diz que não sabe em vez de chutar. Os limites são fixos porque
são decisões de produto, não do sistema.
"""
from __future__ import annotations

import json
import os
import platform
import struct
import sys
import time
from pathlib import Path

import psutil

import config
import ferramentas
import personalidade

RAIZ = Path(__file__).resolve().parent
PACOTE = RAIZ / "electron" / "package.json"

# Decisões de produto: o que o ULTRON não faz, mesmo que pareça capaz.
LIMITES = (
    "não gera nem edita imagens",
    "não edita vídeo",
    "não envia mensagens por WhatsApp",
    "não tem app de celular",
)

# Uma ferramenta pertence a exatamente um grupo. Quem não estiver aqui cai em
# "outras": ferramenta nova aparece na contagem sem quebrar o bloco.
_GRUPOS = {
    "arquivos e pastas": (
        "apagar_arquivo", "compactar_arquivos", "criar_arquivo", "criar_pasta",
        "criar_site", "descompactar_arquivo", "ler_arquivo", "listar_pasta",
        "mover_arquivo", "organizar_arquivos", "prever_organizacao", "procurar_arquivo",
    ),
    "janelas e programas": (
        "abrir_programa", "fechar_aplicativo", "minimizar_janelas", "alternar_modo_escuro",
    ),
    "sistema e hardware": (
        "ajustar_brilho", "ajustar_volume", "bloquear_tela", "cancelar_desligamento",
        "desligar_pc", "info_hardware", "info_sistema", "reiniciar_pc",
        "executar_comando", "rodar_codigo",
    ),
    "web e navegador": (
        "abrir_site", "clicar_pagina", "enviar_formulario", "fechar_navegador",
        "ler_elementos_pagina", "ler_pagina", "navegar", "preencher_campo", "print_pagina",
    ),
    "informação atual": ("clima", "noticias", "pesquisar_web"),
    "tela, mouse e teclado": (
        "ajustar_zoom", "clicar", "clicar_em_texto", "digitar_texto", "ler_texto_tela",
        "localizar_na_tela", "pressionar_tecla", "rolar_tela", "ver_tela",
    ),
    "câmera e gestos": (
        "controlar_mouse_com_gesto", "detectar_gestos_mao", "detectar_objetos", "webcam_foto",
    ),
    "mídia e palco": ("controlar_midia", "mostrar_na_interface", "youtube"),
    "memória e lembretes": (
        "cancelar_lembrete", "criar_lembrete", "esquecer_fato", "lembrar_fato", "listar_lembretes",
        "obsidian_anexar", "obsidian_buscar", "obsidian_criar", "obsidian_diario",
        "obsidian_ler", "obsidian_notas", "obsidian_status", "obsidian_tarefas",
    ),
    "automação": ("executar_fluxo", "listar_jogos"),
    "desfazer": ("desfazer",),
}

_CACHE: dict[str, object] = {"ts": 0.0, "texto": ""}
_VALIDADE = 3600.0  # o processo pode ficar aberto por dias; 1 h é barato e suficiente


def _versao() -> str:
    try:
        dados = json.loads(PACOTE.read_text(encoding="utf-8"))
        versao = str(dados.get("version") or "").strip()
        return versao[:24] or "desconhecida"
    except (OSError, ValueError, AttributeError):
        return "desconhecida"


def _sistema() -> str:
    """SO, build, arquitetura e memória. Sem subprocesso: precisa ser instantâneo."""
    if os.name == "nt":
        try:
            info = sys.getwindowsversion()
            if info.build >= 22000:
                nome = "Windows 11"
            elif info.major >= 10:
                nome = "Windows 10"
            else:
                nome = f"Windows {info.major}.{info.minor}"
            so = f"{nome} (build {info.build})"
        except Exception:
            so = f"Windows {platform.release()}".strip()
    else:
        so = f"{platform.system()} {platform.release()}".strip()
    bits = struct.calcsize("P") * 8
    partes = [so, f"{bits} bits"]
    try:
        nucleos = psutil.cpu_count(logical=False)
        if nucleos:
            partes.append(f"{nucleos} núcleos")
    except Exception:
        pass
    try:
        total = psutil.virtual_memory().total / (1024 ** 3)
        if total >= 1:
            partes.append(f"{total:.0f} GB de RAM")
    except Exception:
        pass
    return ", ".join(partes)


def _grupos() -> tuple[int, str]:
    """Conta as ferramentas registradas e devolve o resumo por grupo."""
    registradas = set(getattr(ferramentas, "FERRAMENTAS", {}) or {})
    contagem: dict[str, int] = {}
    vistas: set[str] = set()
    for grupo, nomes in _GRUPOS.items():
        for nome in nomes:
            if nome in registradas and nome not in vistas:
                contagem[grupo] = contagem.get(grupo, 0) + 1
                vistas.add(nome)
    outras = len(registradas - vistas)
    if outras:
        contagem["outras"] = outras
    ordem = [g for g in _GRUPOS if g in contagem]
    if "outras" in contagem:
        ordem.append("outras")
    resumo = "; ".join(f"{grupo} ({contagem[grupo]})" for grupo in ordem)
    return len(registradas), resumo


def _estatico() -> str:
    """Parte que só muda quando o app é atualizado ou uma ferramenta é registrada."""
    total, resumo = _grupos()
    linhas = [
        f"- Sistema: {_sistema()}.",
        f"- Versão: {_versao()}.",
        "- Limites fixos: " + "; ".join(LIMITES) +
        ". Se pedirem algo assim, diga que não faz e ofereça o que existe.",
        "- Segurança: toda ferramenta passa por um portão único (risco, allowlist e "
        "confirmação); pastas do sistema são protegidas; ação destrutiva pede "
        "confirmação ou PIN, e o que não pode ser desfeito é avisado antes.",
    ]
    if total:
        linhas.insert(2, f"- Habilidades: {total} ferramentas — {resumo}.")
    else:
        linhas.insert(2, "- Habilidades: nenhuma ferramenta registrada neste momento.")
    return "\n".join(linhas)


def bloco(forcar: bool = False) -> str:
    """Bloco curto de autoconhecimento para o system prompt.

    `forcar=True` ignora o cache (usado nos testes e depois de atualizar o app).
    """
    agora = time.time()
    if forcar or not _CACHE["texto"] or agora - float(_CACHE["ts"]) > _VALIDADE:
        try:
            _CACHE["texto"] = _estatico()
        except Exception:
            # Nunca impedir uma resposta por causa do autoconhecimento.
            _CACHE["texto"] = "- Sistema: não consegui ler os dados locais agora."
        _CACHE["ts"] = agora

    try:
        perfil = personalidade.carregar()
        rotulo = str(perfil.get("rotulo") or "ULTRON").strip()
        nome_perfil = str(perfil.get("perfil") or "").strip()
        jeito = str(perfil.get("jeito") or "").strip()
        rotulo_jeito = personalidade.JEITOS.get(jeito, {}).get("rotulo", jeito or "padrão")
    except Exception:
        rotulo, nome_perfil, rotulo_jeito = "ULTRON", "", "padrão"

    identidade = f"- Nome: {rotulo}"
    if nome_perfil:
        identidade += f" (perfil {nome_perfil})"
    identidade += "."

    voz = getattr(config, "VOZ", "") or "padrão"
    return (
        "Autoconhecimento (gerado do sistema agora; não invente além disto):\n"
        f"{identidade}\n"
        f"{_CACHE['texto']}\n"
        f"- Voz: {voz} (Edge TTS; reserva local pyttsx3). Jeito atual: {rotulo_jeito}."
    )
