"""Estado da sessão local do Desktop: bloqueada até um desbloqueio explícito.

Vive só na memória do processo: fechar o app (ou o Windows bloquear/suspender)
encerra a sessão. Não registra log — quem chama decide o que logar, e o PIN
nunca passa por aqui.
"""
import threading
import time

_trava = threading.Lock()
_estado = {"desbloqueada": False, "metodo": None, "desde": None,
           "ultima_atividade": None}

METODOS = ("hello", "pin")


def estado() -> dict:
    with _trava:
        return dict(_estado)


def desbloquear(metodo: str) -> dict:
    if metodo not in METODOS:
        raise ValueError("Método de desbloqueio desconhecido.")
    agora = time.time()
    with _trava:
        _estado.update(desbloqueada=True, metodo=metodo, desde=agora,
                       ultima_atividade=agora)
        return dict(_estado)


def bloquear() -> None:
    with _trava:
        _estado.update(desbloqueada=False, metodo=None, desde=None,
                       ultima_atividade=None)


def tocar() -> None:
    """Marca atividade agora (comando processado): adia o bloqueio por inatividade."""
    with _trava:
        _estado["ultima_atividade"] = time.time()


def ultima_atividade() -> float | None:
    with _trava:
        return _estado["ultima_atividade"]
