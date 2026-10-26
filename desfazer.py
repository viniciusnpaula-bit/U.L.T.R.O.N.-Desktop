"""Desfazer: diário local com a inversa das operações de arquivo do ULTRON.

O diário guarda só o necessário para voltar atrás: o que foi feito, quando e a
operação inversa. Nada é desfeito às cegas:

  * cada inversa confere o estado antes de agir (tamanho, data de modificação,
    destino livre, pasta vazia). Se o item mudou depois da operação, o desfazer
    RECUSA em vez de apagar ou mover algo que o usuário editou;
  * item apagado volta pela Lixeira do Windows, casando pasta original, nome,
    tamanho e data — se houver mais de um parecido, o desfazer não escolhe no
    escuro;
  * caminho protegido (Windows, AppData, .ssh, o próprio ULTRON) nunca é tocado,
    mesmo que o diário tenha sido editado à mão;
  * o diário é atômico, tem trava, TTL e limite de entradas e de tamanho.

O diário é local e não sai do computador. Ele fica em `dados/desfazer/`, dentro
da área protegida do ULTRON.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from config import BASE

DIARIO_DIR = BASE / "dados" / "desfazer"
DIARIO = DIARIO_DIR / "diario.json"

MAX_ENTRADAS = 50
MAX_BYTES = 4 * 1024 * 1024
MAX_ITENS = 5000
TTL = 7 * 24 * 3600          # uma semana para voltar atrás
_ID = re.compile(r"^[a-f0-9]{32}$")
_VERSAO = 1

_trava = threading.Lock()
_trava_undo = threading.Lock()
_log = logging.getLogger("ultron")


# ---------------------------------------------------------------- diário
def _vazio() -> dict:
    return {"versao": _VERSAO, "entradas": []}


def _entrada_valida(entrada) -> bool:
    if not isinstance(entrada, dict):
        return False
    if not isinstance(entrada.get("id"), str) or not _ID.match(entrada["id"]):
        return False
    try:
        expira = float(entrada.get("expira") or 0)
    except (TypeError, ValueError):
        return False
    inversa = entrada.get("inversa")
    if not isinstance(inversa, dict) or not isinstance(inversa.get("tipo"), str):
        return False
    return expira > 0


def _ler() -> dict:
    """Lê o diário; arquivo ausente ou corrompido vira um diário vazio."""
    try:
        dados = json.loads(DIARIO.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _vazio()
    except Exception as erro:
        _log.warning("Diário de desfazer ilegível (%s); começando vazio.", type(erro).__name__)
        return _vazio()
    if not isinstance(dados, dict) or not isinstance(dados.get("entradas"), list):
        return _vazio()
    return {"versao": _VERSAO,
            "entradas": [copy.deepcopy(e) for e in dados["entradas"] if _entrada_valida(e)]}


def _gravar(dados: dict) -> None:
    DIARIO_DIR.mkdir(parents=True, exist_ok=True)
    temporario = DIARIO.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporario, DIARIO)


def _tamanho(entradas: list) -> int:
    return len(json.dumps(entradas, ensure_ascii=False).encode("utf-8"))


def _podar(dados: dict, agora: float | None = None) -> dict:
    """Descarta expiradas e mantém as mais novas, com teto de entradas e de bytes.

    Desfeitas saem primeiro: elas não servem mais para voltar atrás e não devem
    empurrar para fora uma operação que ainda pode ser desfeita.
    """
    agora = time.time() if agora is None else agora
    entradas = [e for e in dados.get("entradas", []) if _entrada_valida(e)
                and float(e.get("expira") or 0) > agora]
    entradas.sort(key=lambda e: (bool(e.get("desfeito")), float(e.get("criado") or 0)))
    while entradas and (len(entradas) > MAX_ENTRADAS or _tamanho(entradas) > MAX_BYTES):
        entradas.pop(0)
    entradas.sort(key=lambda e: float(e.get("criado") or 0))
    return {"versao": _VERSAO, "entradas": entradas}


def registrar(operacao: str, resumo: str, inversa: dict) -> str:
    """Registra uma operação já concluída. Devolve o id; falha de diário não derruba a ação."""
    if not isinstance(inversa, dict) or not inversa.get("tipo"):
        return ""
    agora = time.time()
    entrada = {
        "id": secrets.token_hex(16),
        "criado": agora,
        "expira": agora + TTL,
        "operacao": str(operacao or "arquivo")[:80],
        "resumo": str(resumo or "")[:300],
        "inversa": copy.deepcopy(inversa),
        "desfeito": 0,
    }
    try:
        with _trava:
            dados = _podar(_ler())
            dados["entradas"].append(entrada)
            dados = _podar(dados)
            if not any(e.get("id") == entrada["id"] for e in dados["entradas"]):
                return ""
            _gravar(dados)
    except Exception as erro:
        _log.warning("Não consegui gravar o diário de desfazer (%s).", type(erro).__name__)
        return ""
    return entrada["id"]


def _obter(identificador: str, agora: float | None = None) -> dict | None:
    identificador = str(identificador or "").strip().lower()
    if not _ID.match(identificador):
        return None
    with _trava:
        dados = _podar(_ler(), agora)
    for entrada in dados["entradas"]:
        if entrada["id"] == identificador:
            return copy.deepcopy(entrada)
    return None


def proxima(agora: float | None = None) -> dict | None:
    """A operação mais recente que ainda pode ser desfeita."""
    with _trava:
        dados = _podar(_ler(), agora)
    for entrada in reversed(dados["entradas"]):
        if not entrada.get("desfeito"):
            return copy.deepcopy(entrada)
    return None


def listar(limite: int = 10) -> list[dict]:
    """Resumo das operações recentes, para inspeção do diário."""
    with _trava:
        dados = _podar(_ler())
    saida = []
    for entrada in reversed(dados["entradas"][-max(1, int(limite)):]):
        saida.append({"id": entrada["id"], "operacao": entrada["operacao"],
                      "resumo": entrada["resumo"], "desfeito": bool(entrada.get("desfeito")),
                      "criado": entrada["criado"]})
    return saida


def resumo_inversa(entrada: dict) -> str:
    """Frase do que o desfazer vai fazer, para a pergunta de confirmação."""
    inversa = entrada.get("inversa") or {}
    tipo = inversa.get("tipo")
    caminho = str(inversa.get("caminho") or "")
    if tipo == "restaurar_lixeira":
        return f"restaurar {caminho} da Lixeira"
    if tipo == "remover":
        return f"apagar {caminho}, que o ULTRON criou"
    if tipo == "remover_pasta":
        return f"apagar a pasta {caminho}, que o ULTRON criou"
    if tipo == "remover_arvore":
        return f"apagar a pasta extraída {caminho}"
    if tipo == "mover":
        itens = inversa.get("itens") or []
        if len(itens) == 1:
            return f"devolver {itens[0].get('de')} para {itens[0].get('para')}"
        return f"devolver {len(itens)} arquivo(s) para as pastas de origem"
    return str(entrada.get("resumo") or entrada.get("operacao") or "a última operação")


def _marcar(identificador: str, **campos) -> None:
    with _trava:
        dados = _podar(_ler())
        for entrada in dados["entradas"]:
            if entrada["id"] == identificador:
                entrada.update(campos)
                break
        _gravar(dados)


# ---------------------------------------------------------------- caminhos
def _absoluto(valor) -> Path | None:
    try:
        p = Path(str(valor)).expanduser()
        return p.resolve() if p.is_absolute() else None
    except Exception:
        return None


def _impressao(p: Path) -> dict:
    """Tamanho e data de modificação: a impressão digital usada para conferir depois."""
    try:
        if p.is_dir():
            return {"pasta": True}
        info = p.stat()
        return {"tamanho": int(info.st_size), "mtime_ns": int(info.st_mtime_ns)}
    except OSError:
        return {}


def _mesma_impressao(p: Path, dados: dict) -> bool:
    if dados.get("pasta"):
        return p.is_dir()
    try:
        if not p.is_file():
            return False
        info = p.stat()
    except OSError:
        return False
    if dados.get("tamanho") is not None and info.st_size != int(dados["tamanho"]):
        return False
    if dados.get("mtime_ns") is not None and info.st_mtime_ns != int(dados["mtime_ns"]):
        return False
    return True


def _protegido(p: Path) -> bool:
    try:
        import ferramentas
        return bool(ferramentas._protegido(str(p)))
    except Exception:
        return True      # na dúvida, não toca


def _motivo_recusa(p: Path) -> str:
    """Mesma régua de `apagar_arquivo`: nada protegido, nada fora da casa/allowlist."""
    if _protegido(p):
        return "o caminho está em uma área protegida do sistema"
    casa = Path.home().resolve()
    if p == casa or casa in p.parents:
        return ""
    try:
        import ferramentas
        if ferramentas._pasta_ok(str(p)):
            return ""
    except Exception:
        pass
    return "o caminho está fora da pasta do usuário e da allowlist"


def _limpar_pastas(pastas) -> None:
    """Remove só pastas vazias que o ULTRON criou, da mais funda para a mais rasa."""
    if not isinstance(pastas, list):
        return
    ordenadas = sorted(pastas, key=lambda v: len(Path(str(v)).parts), reverse=True)
    for valor in ordenadas:
        p = _absoluto(valor)
        if p is None or not p.is_dir() or _motivo_recusa(p):
            continue
        try:
            p.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------- inversas
def inversa_remover(caminho, pastas_criadas=()) -> dict:
    """Inversa de criar um arquivo: apagá-lo se ainda estiver igual."""
    p = _absoluto(caminho)
    if p is None:
        raise ValueError("caminho inválido")
    return {"tipo": "remover", "caminho": str(p), **_impressao(p),
            "pastas_criadas": [str(x) for x in pastas_criadas]}


def inversa_remover_pasta(caminho, pastas_criadas=()) -> dict:
    """Inversa de criar uma pasta: removê-la só se continuar vazia."""
    p = _absoluto(caminho)
    if p is None:
        raise ValueError("caminho inválido")
    return {"tipo": "remover_pasta", "caminho": str(p),
            "pastas_criadas": [str(x) for x in pastas_criadas]}


def inversa_mover(itens, pastas_criadas=()) -> dict:
    """Inversa de mover/renomear.

    `itens` é uma lista de dicionários com `de` (onde está agora), `para` (onde
    deve voltar) e, opcionalmente, `de_antes` (o caminho a fotografar antes da
    movimentação). O `mtime` é preservado pelo move, então a foto vale depois.
    """
    montados = []
    for item in itens or []:
        de = _absoluto(item.get("de"))
        para = _absoluto(item.get("para"))
        if de is None or para is None:
            raise ValueError("caminho inválido")
        origem = _absoluto(item.get("de_antes")) or de
        montados.append({"de": str(de), "para": str(para), **_impressao(origem)})
    if not montados:
        raise ValueError("nada para mover")
    if len(montados) > MAX_ITENS:
        raise ValueError("movimentação grande demais para o diário")
    return {"tipo": "mover", "itens": montados,
            "pastas_criadas": [str(x) for x in pastas_criadas]}


def inversa_restaurar(caminho) -> dict:
    """Inversa de apagar: restaurar da Lixeira, casando pasta, nome e impressão."""
    p = _absoluto(caminho)
    if p is None:
        raise ValueError("caminho inválido")
    return {"tipo": "restaurar_lixeira", "caminho": str(p), **_impressao(p)}


def inversa_arvore(caminho, remover_raiz: bool = True) -> dict:
    """Inversa de extrair um ZIP: apagar exatamente o que foi criado."""
    p = _absoluto(caminho)
    if p is None or not p.is_dir():
        raise ValueError("pasta inválida")
    arquivos, pastas = [], []
    for raiz, subpastas, nomes in os.walk(p, followlinks=False):
        for nome in subpastas:
            alvo = Path(raiz, nome)
            if alvo.is_symlink():
                raise ValueError("a árvore tem link simbólico")
            pastas.append(str(alvo.relative_to(p)))
        for nome in nomes:
            alvo = Path(raiz, nome)
            if alvo.is_symlink():
                raise ValueError("a árvore tem link simbólico")
            info = alvo.stat()
            arquivos.append([str(alvo.relative_to(p)), int(info.st_size), int(info.st_mtime_ns)])
            if len(arquivos) > MAX_ITENS:
                raise ValueError("árvore grande demais para o diário")
    return {"tipo": "remover_arvore", "caminho": str(p),
            "arquivos": arquivos, "pastas": pastas, "remover_raiz": bool(remover_raiz)}


# ---------------------------------------------------------------- aplicar
def _ok(mensagem: str, **extra) -> dict:
    return {"ok": True, "mensagem": mensagem, **extra}


def _falha(mensagem: str, **extra) -> dict:
    return {"ok": False, "mensagem": "Não desfiz: " + mensagem, **extra}


def _aplicar_remover(dados: dict) -> dict:
    p = _absoluto(dados.get("caminho"))
    if p is None:
        return _falha("o caminho registrado não é válido.")
    motivo = _motivo_recusa(p)
    if motivo:
        return _falha(motivo + ".")
    if not p.exists():
        _limpar_pastas(dados.get("pastas_criadas"))
        return _ok("o arquivo já não existia; nada a apagar.")
    if p.is_dir():
        return _falha("o registro esperava um arquivo, mas o caminho agora é uma pasta.")
    if not _mesma_impressao(p, dados):
        return _falha("o arquivo mudou depois da operação; não vou apagar o que você editou.")
    p.unlink()
    _limpar_pastas(dados.get("pastas_criadas"))
    return _ok(f"apaguei {p}, que tinha sido criado pelo ULTRON.")


def _aplicar_remover_pasta(dados: dict) -> dict:
    p = _absoluto(dados.get("caminho"))
    if p is None:
        return _falha("o caminho registrado não é válido.")
    motivo = _motivo_recusa(p)
    if motivo:
        return _falha(motivo + ".")
    if not p.exists():
        _limpar_pastas(dados.get("pastas_criadas"))
        return _ok("a pasta já não existia; nada a apagar.")
    if not p.is_dir():
        return _falha("o caminho agora é um arquivo, não a pasta criada.")
    try:
        if any(p.iterdir()):
            return _falha("a pasta não está vazia; não vou apagar o que você colocou nela.")
        p.rmdir()
    except OSError as erro:
        return _falha(f"o Windows não deixou remover a pasta ({erro.strerror or erro}).")
    _limpar_pastas(dados.get("pastas_criadas"))
    return _ok(f"apaguei a pasta vazia {p}.")


def _aplicar_mover(dados: dict) -> dict:
    itens = dados.get("itens")
    if not isinstance(itens, list) or not itens:
        return _falha("o diário não tem os caminhos dessa movimentação.")
    preparados = []
    for item in itens:
        if not isinstance(item, dict):
            return _falha("o diário está corrompido.")
        de = _absoluto(item.get("de"))
        para = _absoluto(item.get("para"))
        if de is None or para is None:
            return _falha("o diário tem um caminho inválido.")
        if _motivo_recusa(de) or _motivo_recusa(para):
            return _falha("um dos caminhos está fora da pasta do usuário e da allowlist.")
        if not de.exists():
            return _falha(f"{de.name} já não está onde foi deixado; nada foi movido.")
        if para.exists():
            return _falha(f"já existe algo em {para}; não vou sobrescrever.")
        if not _mesma_impressao(de, item):
            return _falha(f"{de.name} mudou depois da operação; não vou movê-lo.")
        preparados.append((de, para))

    movidos, falhas = 0, []
    pendentes = []
    for item, (de, para) in zip(itens, preparados):
        try:
            para.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(de), str(para))
            movidos += 1
        except OSError as erro:
            falhas.append(f"{de.name}: {erro.strerror or erro}")
            pendentes.append(item)
    _limpar_pastas(dados.get("pastas_criadas"))
    if falhas:
        return _falha(f"movi {movidos} de {len(itens)} de volta; falhou em "
                      + "; ".join(falhas[:3]) + ".", restantes=pendentes)
    if len(preparados) == 1:
        return _ok(f"devolvi {preparados[0][0].name} para {preparados[0][1]}.")
    return _ok(f"devolvi {movidos} arquivo(s) para as pastas de origem.")


def _item_confere(item, dados: dict) -> bool:
    """O item da Lixeira parece o mesmo arquivo que foi apagado?"""
    try:
        tamanho = int(item.ExtendedProperty("System.Size"))
    except Exception:
        tamanho = None
    if not dados.get("pasta") and dados.get("tamanho") is not None and tamanho is not None:
        if tamanho != int(dados["tamanho"]):
            return False
    try:
        modificado = item.ExtendedProperty("System.DateModified")
        if modificado is not None and dados.get("mtime_ns") is not None:
            if abs(float(modificado.timestamp()) - int(dados["mtime_ns"]) / 1e9) > 2:
                return False
    except Exception:
        pass
    return True


def _verbo_restaurar(item):
    try:
        verbos = list(item.Verbs())
    except Exception:
        return None
    for verbo in verbos:
        nome = (verbo.Name or "").replace("&", "").strip().lower()
        if "restaur" in nome or "restore" in nome:
            return verbo
    return None


def _restaurar_da_lixeira(caminho: Path, dados: dict) -> tuple[bool, str]:
    """Restaura um item da Lixeira pelo Shell do Windows, sem abrir a janela dela."""
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return False, ("não tenho o componente do Windows (pywin32) para restaurar da Lixeira; "
                       "abra a Lixeira e restaure o item manualmente")
    pasta = os.path.normcase(os.path.normpath(str(caminho.parent)))
    nome = caminho.name.lower()
    candidatos = []
    pythoncom.CoInitialize()
    try:
        lixeira = win32com.client.Dispatch("Shell.Application").NameSpace(10)
        if lixeira is None:
            return False, "não consegui abrir a Lixeira do Windows"
        for item in lixeira.Items():
            try:
                origem = str(item.ExtendedProperty("System.Recycle.DeletedFrom") or "")
            except Exception:
                continue
            if (os.path.normcase(os.path.normpath(origem)) == pasta
                    and str(item.Name).lower() == nome):
                candidatos.append(item)
        if not candidatos:
            return False, "não achei esse item na Lixeira; talvez ela tenha sido esvaziada"
        if len(candidatos) > 1:
            candidatos = [item for item in candidatos if _item_confere(item, dados)]
            if len(candidatos) != 1:
                return False, ("há mais de um item parecido na Lixeira; "
                               "restaure manualmente para não pegar o errado")
        verbo = _verbo_restaurar(candidatos[0])
        if verbo is None:
            return False, ("não achei o comando de restaurar nesta versão do Windows; "
                           "abra a Lixeira e restaure manualmente")
        verbo.DoIt()
    except Exception as erro:
        return False, f"o Windows recusou a restauração ({type(erro).__name__})"
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    for _ in range(24):
        if caminho.exists():
            return True, ""
        time.sleep(0.25)
    return False, "o Windows não restaurou o item a tempo; confira a Lixeira"


def _aplicar_restaurar(dados: dict, restaurador=None) -> dict:
    p = _absoluto(dados.get("caminho"))
    if p is None:
        return _falha("o caminho registrado não é válido.")
    motivo = _motivo_recusa(p)
    if motivo:
        return _falha(motivo + ".")
    if p.exists():
        return _falha(f"já existe algo em {p}; não vou sobrescrever.")
    restaurar = restaurador or _restaurar_da_lixeira
    try:
        sucesso, motivo = restaurar(p, dados)
    except Exception as erro:
        return _falha(f"a restauração falhou ({type(erro).__name__}).")
    if not sucesso:
        return _falha(str(motivo or "não consegui restaurar o item") + ".")
    if not p.exists():
        return _falha("o Windows disse que restaurou, mas o item não apareceu.")
    if p.is_file() and dados.get("tamanho") is not None:
        try:
            if p.stat().st_size != int(dados["tamanho"]):
                return _ok(f"restaurei {p} da Lixeira, mas o tamanho não confere com o original. "
                           "Confira o conteúdo antes de usar.")
        except OSError:
            pass
    return _ok(f"restaurei {p} da Lixeira.")


def _aplicar_arvore(dados: dict) -> dict:
    p = _absoluto(dados.get("caminho"))
    if p is None:
        return _falha("o caminho registrado não é válido.")
    motivo = _motivo_recusa(p)
    if motivo:
        return _falha(motivo + ".")
    if not p.exists():
        return _ok("a pasta extraída já não existia; nada a apagar.")
    if not p.is_dir():
        return _falha("o caminho agora é um arquivo, não a pasta extraída.")
    esperados = {}
    for registro in dados.get("arquivos") or []:
        if not isinstance(registro, list) or len(registro) != 3:
            return _falha("o diário está corrompido.")
        esperados[str(registro[0])] = (int(registro[1]), int(registro[2]))
    pastas_esperadas = {str(x) for x in dados.get("pastas") or []}
    arquivos, pastas = {}, set()
    for raiz, subpastas, nomes in os.walk(p, followlinks=False):
        for nome in subpastas:
            alvo = Path(raiz, nome)
            if alvo.is_symlink():
                return _falha("a pasta agora tem um link simbólico; não vou apagar.")
            pastas.add(str(alvo.relative_to(p)))
        for nome in nomes:
            alvo = Path(raiz, nome)
            if alvo.is_symlink():
                return _falha("a pasta agora tem um link simbólico; não vou apagar.")
            try:
                info = alvo.stat()
            except OSError:
                return _falha("não consegui conferir todos os arquivos extraídos.")
            arquivos[str(alvo.relative_to(p))] = (int(info.st_size), int(info.st_mtime_ns))
    if set(arquivos) != set(esperados) or pastas != pastas_esperadas:
        return _falha("a pasta extraída mudou depois da operação; não vou apagar nada.")
    for relativo, (tamanho, mtime) in arquivos.items():
        if esperados[relativo] != (tamanho, mtime):
            return _falha(f"{relativo} mudou depois da extração; não vou apagar nada.")
    for relativo in sorted(arquivos, key=lambda x: len(Path(x).parts), reverse=True):
        try:
            (p / relativo).unlink()
        except OSError as erro:
            return _falha(f"o Windows não deixou apagar {relativo} ({erro.strerror or erro}).")
    for relativo in sorted(pastas, key=lambda x: len(Path(x).parts), reverse=True):
        try:
            (p / relativo).rmdir()
        except OSError:
            pass
    if dados.get("remover_raiz"):
        try:
            p.rmdir()
        except OSError:
            pass
    return _ok(f"apaguei a pasta extraída {p}.")


def _aplicar(entrada: dict, restaurador=None) -> dict:
    inversa = entrada.get("inversa") or {}
    tipo = inversa.get("tipo")
    try:
        if tipo == "remover":
            return _aplicar_remover(inversa)
        if tipo == "remover_pasta":
            return _aplicar_remover_pasta(inversa)
        if tipo == "mover":
            return _aplicar_mover(inversa)
        if tipo == "restaurar_lixeira":
            return _aplicar_restaurar(inversa, restaurador)
        if tipo == "remover_arvore":
            return _aplicar_arvore(inversa)
    except Exception as erro:
        return _falha(f"a operação inversa falhou ({type(erro).__name__}).")
    return _falha("o diário não sabe desfazer essa operação.")


# ---------------------------------------------------------------- público
def desfazer(identificador: str = "", *, restaurador=None, agora: float | None = None) -> dict:
    """Desfaz a última operação (ou uma específica, pelo id).

    Devolve `{"ok", "mensagem", "id"}`. Tudo é conferido antes de tocar no disco;
    se algo mudou desde a operação original, nada é apagado nem movido.
    """
    identificador = str(identificador or "").strip().lower()
    if identificador and not _ID.match(identificador):
        return {"ok": False, "mensagem": "Não desfiz: o id da operação não é válido."}
    entrada = _obter(identificador, agora) if identificador else proxima(agora)
    if entrada is None:
        if identificador:
            return {"ok": False, "mensagem": "Não encontrei essa operação no diário; ela pode ter expirado."}
        return {"ok": False, "mensagem": "Não há nada para desfazer no diário (as últimas operações de arquivo)."}
    if entrada.get("desfeito"):
        return {"ok": False, "mensagem": "Essa operação já foi desfeita."}
    with _trava_undo:
        resultado = _aplicar(entrada, restaurador)
        if resultado.get("ok"):
            _marcar(entrada["id"], desfeito=time.time())
        elif resultado.get("restantes"):
            _marcar(entrada["id"], inversa={**entrada["inversa"],
                                            "itens": resultado["restantes"]})
    resultado["id"] = entrada["id"]
    return resultado
