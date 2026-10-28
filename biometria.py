"""Windows Hello (UserConsentVerifier) com import preguiçoso e prazo.

A biometria é do Windows: o ULTRON nunca recebe template, hash nem imagem. Sem o
pacote, sem sensor ou com o prompt fechado, tudo devolve indisponível/negado —
nunca levanta para a API (exceto `Ocupado`, que é um estado esperado).
"""
import asyncio
import threading

PRAZO_S = 60.0            # o prompt do Windows pode ficar aberto; a thread do servidor não espera
PRAZO_DISPONIVEL_S = 10.0

_TRAVA = threading.Lock()

# Códigos estáveis do WinRT (AVAILABLE e VERIFIED são 0).
_MOTIVOS = {
    0: "Windows Hello pronto",
    1: "Nenhum sensor de Windows Hello neste PC",
    2: "Windows Hello não está configurado para este usuário",
    3: "Windows Hello desativado por política",
    4: "Sensor do Windows Hello ocupado",
}


class Ocupado(RuntimeError):
    """Já existe um pedido do Windows Hello aberto."""


def _winrt():
    """(verificador, disponibilidade, resultado, iniciar_apartamento) ou None."""
    try:
        import winrt
        from winrt.runtime import ApartmentType, init_apartment
        from winrt.windows.security.credentials.ui import (
            UserConsentVerificationResult, UserConsentVerifier, UserConsentVerifierAvailability)
    except Exception:
        return None

    def iniciar():
        # winrt-runtime 4.x moveu init_apartment para winrt.runtime e exige o tipo
        # de apartamento; versões antigas expõem winrt.init_apartment() sem args.
        if hasattr(winrt, "init_apartment"):
            winrt.init_apartment()
        else:
            init_apartment(ApartmentType.MULTI_THREADED)

    return (UserConsentVerifier, UserConsentVerifierAvailability,
            UserConsentVerificationResult, iniciar)


def _executar(fabrica, prazo):
    """Roda a chamada WinRT numa thread própria com prazo. None = indisponível/estourou."""
    caixa = {}

    def alvo():
        api = _winrt()
        if api is None:
            caixa["valor"] = None
            return
        try:
            api[3]()          # init_apartment na MESMA thread do asyncio.run
        except Exception:
            pass              # já inicializado (ou recusado): a chamada abaixo decide
        try:
            caixa["valor"] = asyncio.run(fabrica(api))
        except Exception:
            caixa["valor"] = None

    thread = threading.Thread(target=alvo, name="ultron-hello", daemon=True)
    thread.start()
    thread.join(prazo)
    if thread.is_alive():
        return None           # prompt segue aberto; o usuário fecha, a thread é daemon
    return caixa.get("valor")


def disponivel() -> dict:
    valor = _executar(lambda api: api[0].check_availability_async(), PRAZO_DISPONIVEL_S)
    try:
        codigo = int(valor)
    except (TypeError, ValueError):
        return {"disponivel": False, "motivo": "Windows Hello indisponível"}
    return {"disponivel": codigo == 0, "motivo": _MOTIVOS.get(codigo, "Windows Hello indisponível")}


def verificar(motivo: str = "Desbloquear o ULTRON") -> bool:
    if not _TRAVA.acquire(blocking=False):
        raise Ocupado("Já existe um pedido do Windows Hello em andamento.")
    try:
        valor = _executar(lambda api: api[0].request_verification_async(str(motivo)[:128]), PRAZO_S)
        try:
            return int(valor) == 0        # VERIFIED
        except (TypeError, ValueError):
            return False
    finally:
        _TRAVA.release()
