"""Navegador controlado por Playwright, em uma thread própria.

Por que uma thread: a API síncrona do Playwright pertence à thread que a criou.
O ULTRON chama ferramentas da voz, do teclado e da interface — threads diferentes.
Aqui existe UMA thread dona do navegador; as outras só pedem e esperam a resposta.

O que este módulo recusa, por decisão de segurança:
  * qualquer esquema que não seja http/https (file:, javascript:, data:);
  * endereço com usuário/senha embutido;
  * host local ou de rede privada (localhost, 127.0.0.1, 10.x, 192.168.x, ...);
  * preencher campo de senha, cartão, token ou CVV;
  * download de arquivos (o navegador cancela).

Ele NÃO é um sandbox: a página vê o IP da máquina, como qualquer navegador.
Textos da página são dados, nunca ordens — quem garante isso é o prompt do cérebro.
"""
from __future__ import annotations

import atexit
import importlib.util
import ipaddress
import queue
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

TEMPO_PADRAO = 45.0
TEMPO_NAVEGAR = 25.0
MAX_TEXTO = 6000
MAX_ELEMENTOS = 80

_CAMPOS_PROIBIDOS = ("senha", "password", "passwd", "token", "secret", "segredo",
                     "cvv", "cvc", "cartao", "cartão", "card", "pin", "api_key", "apikey")


class NavegadorErro(RuntimeError):
    """Falha explicável: a ferramenta devolve a mensagem, nunca um stack trace."""


class NavegadorIndisponivel(NavegadorErro):
    """Playwright não instalado."""


def disponivel() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _parece_local(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in {"localhost", "localhost.localdomain"} or h.endswith((".local", ".internal", ".lan", ".home")):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved


def _resolver_publico(host: str, timeout: float = 3.0) -> bool:
    """Resolve o host e diz se TODOS os endereços são públicos. Timeout = deixa o navegador decidir."""
    resultado: dict = {}

    def resolver():
        try:
            resultado["ips"] = {info[4][0] for info in socket.getaddrinfo(host, None)}
        except OSError as erro:
            resultado["erro"] = erro

    thread = threading.Thread(target=resolver, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive() or "ips" not in resultado:
        return True
    for texto in resultado["ips"]:
        try:
            ip = ipaddress.ip_address(texto)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    return True


def validar_url(url: str) -> str:
    """Devolve a URL normalizada ou levanta NavegadorErro explicando o motivo."""
    bruta = str(url or "").strip()
    if not bruta:
        raise NavegadorErro("faltou o endereço.")
    partes = urlparse(bruta)
    if partes.scheme and partes.scheme.lower() not in {"http", "https"}:
        raise NavegadorErro("só abro endereços http:// ou https://.")
    if not bruta.startswith(("http://", "https://")):
        bruta = "https://" + bruta
    partes = urlparse(bruta)
    if partes.scheme not in {"http", "https"}:
        raise NavegadorErro("só abro endereços http:// ou https://.")
    if partes.username or partes.password:
        raise NavegadorErro("não abro endereço com usuário/senha embutidos.")
    host = partes.hostname or ""
    if not host:
        raise NavegadorErro("o endereço não tem um domínio válido.")
    if _parece_local(host) or not _resolver_publico(host):
        raise NavegadorErro("não abro endereço da rede local (localhost, 127.0.0.1, 192.168.x...).")
    return bruta


# ---------------------------------------------------------------------------
# Thread dona do navegador
# ---------------------------------------------------------------------------
_fila: "queue.Queue" = queue.Queue()
_trava = threading.Lock()
_thread: threading.Thread | None = None
_estado: dict = {}


def _iniciar(estado: dict):
    if estado.get("page") is not None:
        return
    if not disponivel():
        raise NavegadorIndisponivel(
            "o navegador controlado precisa do Playwright (pip install playwright). "
            "Enquanto isso, abrir_site abre o seu navegador normal.")
    from playwright.sync_api import sync_playwright

    estado["pw"] = sync_playwright().start()
    erros = []
    navegador = None
    for opcoes in ({"channel": "msedge", "headless": False}, {"headless": False}):
        try:
            navegador = estado["pw"].chromium.launch(**opcoes)
            break
        except Exception as erro:
            erros.append(f"{type(erro).__name__}: {erro}")
    if navegador is None:
        estado["pw"].stop()
        estado["pw"] = None
        raise NavegadorErro(
            "não consegui abrir o navegador. Instale o Chromium do Playwright "
            "(python -m playwright install chromium). Detalhe: " + " | ".join(erros)[:300])
    estado["browser"] = navegador
    contexto = navegador.new_context(
        locale="pt-BR", viewport={"width": 1280, "height": 800},
        accept_downloads=False, java_script_enabled=True,
    )
    pagina = contexto.new_page()
    pagina.set_default_timeout(15000)

    def _fechar_dialogo(dialogo):
        try:
            dialogo.dismiss()
        except Exception:
            pass

    def _cancelar_download(download):
        try:
            download.cancel()
        except Exception:
            pass

    pagina.on("dialog", _fechar_dialogo)
    pagina.on("download", _cancelar_download)
    estado.update(context=contexto, page=pagina)


def _fechar(estado: dict):
    for chave in ("context", "browser"):
        alvo = estado.get(chave)
        if alvo is not None:
            try:
                alvo.close()
            except Exception:
                pass
    if estado.get("pw") is not None:
        try:
            estado["pw"].stop()
        except Exception:
            pass
    estado.clear()


def _loop():
    while True:
        fn, args, resposta = _fila.get()
        if fn is None:
            _fechar(_estado)
            return
        try:
            resposta["valor"] = fn(_estado, *args)
        except NavegadorErro as erro:
            resposta["erro"] = str(erro)
        except Exception as erro:
            resposta["erro"] = f"{type(erro).__name__}: {erro}"
        finally:
            resposta["evento"].set()


def _garantir_thread():
    global _thread
    with _trava:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, name="ultron-navegador", daemon=True)
        _thread.start()


def _chamar(fn, *args, timeout: float = TEMPO_PADRAO):
    _garantir_thread()
    resposta = {"evento": threading.Event(), "valor": None, "erro": None}
    _fila.put((fn, args, resposta))
    if not resposta["evento"].wait(timeout):
        raise NavegadorErro("o navegador demorou demais para responder; a página pode estar travada.")
    if resposta["erro"]:
        raise NavegadorErro(resposta["erro"])
    return resposta["valor"]


def aberto() -> bool:
    return _estado.get("page") is not None


def _fechar_no_exit():
    if _thread is not None and _thread.is_alive():
        _fila.put((None, (), {"evento": threading.Event(), "valor": None, "erro": None}))


atexit.register(_fechar_no_exit)


# ---------------------------------------------------------------------------
# Comandos (rodam na thread do navegador)
# ---------------------------------------------------------------------------
def _cmd_navegar(estado, url):
    _iniciar(estado)
    pagina = estado["page"]
    try:
        pagina.goto(url, wait_until="domcontentloaded", timeout=int(TEMPO_NAVEGAR * 1000))
    except Exception as erro:
        raise NavegadorErro(f"não consegui abrir {url}: {str(erro)[:200]}")
    return {"url": pagina.url, "titulo": pagina.title()[:200]}


def _cmd_texto(estado):
    _iniciar(estado)
    pagina = estado["page"]
    try:
        texto = pagina.inner_text("body", timeout=10000)
    except Exception as erro:
        raise NavegadorErro(f"não consegui ler a página: {str(erro)[:200]}")
    limpo = " ".join(texto.split())
    return {"url": pagina.url, "titulo": pagina.title()[:200], "texto": limpo[:MAX_TEXTO],
            "truncado": len(limpo) > MAX_TEXTO}


_JS_ELEMENTOS = """
() => {
  const seletor = 'a,button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=tab],[contenteditable=true]';
  const vistos = new Set();
  const saida = [];
  for (const el of document.querySelectorAll(seletor)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const estilo = getComputedStyle(el);
    if (estilo.visibility === 'hidden' || estilo.display === 'none') continue;
    const nome = (el.innerText || el.value || el.getAttribute('aria-label') ||
                  el.getAttribute('placeholder') || el.name || el.id || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    if (!nome || vistos.has(nome + '|' + r.x + '|' + r.y)) continue;
    vistos.add(nome + '|' + r.x + '|' + r.y);
    saida.push({
      tag: el.tagName.toLowerCase(),
      tipo: (el.type || '').toLowerCase(),
      nome: nome,
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2)
    });
    if (saida.length >= %d) break;
  }
  return saida;
}
""" % MAX_ELEMENTOS


def _cmd_elementos(estado):
    _iniciar(estado)
    pagina = estado["page"]
    try:
        elementos = pagina.evaluate(_JS_ELEMENTOS)
    except Exception as erro:
        raise NavegadorErro(f"não consegui listar os elementos: {str(erro)[:200]}")
    return {"url": pagina.url, "titulo": pagina.title()[:200], "elementos": elementos or []}


def _cmd_clicar(estado, texto):
    _iniciar(estado)
    pagina = estado["page"]
    alvo = str(texto or "").strip()
    if not alvo:
        raise NavegadorErro("diga o texto do botão ou link.")
    candidatos = [
        pagina.get_by_role("button", name=alvo, exact=False),
        pagina.get_by_role("link", name=alvo, exact=False),
        pagina.get_by_role("menuitem", name=alvo, exact=False),
        pagina.get_by_text(alvo, exact=False),
    ]
    for localizador in candidatos:
        try:
            total = localizador.count()
        except Exception:
            continue
        if total == 0:
            continue
        for indice in range(min(total, 5)):
            item = localizador.nth(indice)
            try:
                if item.is_visible():
                    item.click(timeout=8000)
                    return {"ok": True, "url": pagina.url, "titulo": pagina.title()[:200]}
            except Exception:
                continue
    raise NavegadorErro(f"não encontrei nada clicável com “{alvo}” na página.")


def _cmd_preencher(estado, campo, valor):
    _iniciar(estado)
    pagina = estado["page"]
    nome = str(campo or "").strip()
    if not nome:
        raise NavegadorErro("diga o nome ou o rótulo do campo.")
    if any(p in nome.lower() for p in _CAMPOS_PROIBIDOS):
        raise NavegadorErro("não preencho campo de senha, cartão, token ou PIN. Faça isso você mesmo.")
    candidatos = [
        pagina.get_by_label(nome, exact=False),
        pagina.get_by_placeholder(nome, exact=False),
        pagina.locator(f'input[name="{nome}"], textarea[name="{nome}"]'),
    ]
    for localizador in candidatos:
        try:
            total = localizador.count()
        except Exception:
            continue
        if total == 0:
            continue
        item = localizador.first
        try:
            if not item.is_visible() or not item.is_editable():
                continue
            tipo = (item.get_attribute("type") or "").lower()
            autocomplete = (item.get_attribute("autocomplete") or "").lower()
            if tipo in {"password", "hidden", "file"} or "password" in autocomplete:
                raise NavegadorErro("esse campo é de senha ou de arquivo; não preencho.")
            item.fill(str(valor), timeout=8000)
            return {"ok": True, "campo": nome, "url": pagina.url}
        except NavegadorErro:
            raise
        except Exception:
            continue
    raise NavegadorErro(f"não encontrei um campo editável com “{nome}”.")


def _cmd_enviar(estado, botao=""):
    _iniciar(estado)
    pagina = estado["page"]
    alvo = str(botao or "").strip()
    if alvo:
        return _cmd_clicar(estado, alvo)
    try:
        pagina.keyboard.press("Enter")
    except Exception as erro:
        raise NavegadorErro(f"não consegui enviar: {str(erro)[:200]}")
    return {"ok": True, "url": pagina.url, "titulo": pagina.title()[:200]}


def _cmd_print(estado):
    _iniciar(estado)
    pagina = estado["page"]
    pasta = Path.home() / "Pictures" / "ULTRON"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"pagina-{time.strftime('%Y%m%d-%H%M%S')}.png"
    try:
        pagina.screenshot(path=str(destino), full_page=False)
    except Exception as erro:
        raise NavegadorErro(f"não consegui tirar o print: {str(erro)[:200]}")
    return {"ok": True, "arquivo": str(destino), "url": pagina.url}


def _cmd_fechar(estado):
    _fechar(estado)
    return {"ok": True}


# ---------------------------------------------------------------------------
# API pública (chamada pelas ferramentas)
# ---------------------------------------------------------------------------
def navegar(url: str) -> dict:
    return _chamar(_cmd_navegar, validar_url(url), timeout=TEMPO_NAVEGAR + 10)


def ler_texto() -> dict:
    return _chamar(_cmd_texto)


def ler_elementos() -> dict:
    return _chamar(_cmd_elementos)


def clicar(texto: str) -> dict:
    return _chamar(_cmd_clicar, texto)


def preencher(campo: str, valor: str) -> dict:
    return _chamar(_cmd_preencher, campo, valor)


def enviar(botao: str = "") -> dict:
    return _chamar(_cmd_enviar, botao)


def print_pagina() -> dict:
    return _chamar(_cmd_print)


def fechar() -> dict:
    return _chamar(_cmd_fechar)
