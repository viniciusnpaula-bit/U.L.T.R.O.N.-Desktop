"""ULTRON - ponto de entrada.
   python main.py                  -> modo voz com janela
   python main.py --bandeja        -> modo voz em segundo plano, com ícone na bandeja (sem janela)
   python main.py --texto          -> só terminal
   python main.py --instalar-inicio / --remover-inicio   -> iniciar junto com o Windows
   python main.py --testar                               -> testes locais (roda pytest)"""
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import config
import sessao
import biometria

# Sem janela (pythonw) não existe saída de texto: manda tudo para um arquivo.
if sys.stdout is None or sys.stderr is None or "--bandeja" in sys.argv:
    sys.stdout = sys.stderr = open(config.BASE / "logs" / "console.log", "a", buffering=1, encoding="utf-8")

import cerebro
import confirmacao
import fala
import memoria
import personalidade
import seguranca
import teclado

WAKE = re.compile(r"(?:\b(?:ei|hey|oi|ouça|e aí)\b[\s,]*)?\b(ultr[oa]n|ultrom|ultra on|altron)\b[\s,.!?]*")


def _detectar_correcao_pessoal(texto: str) -> tuple[str | None, str] | None:
    """Detecta 'não, eu disse X' (ou variantes) e devolve (ouvido_errado, dito_certo).

    `ouvido_errado` é None quando o padrão não traz um par explícito (usamos
    então o último reconhecimento do usuário).
    """
    t = texto.strip()
    padroes = (
        r"^nao,? eu disse (.+)$",
        r"^não,? eu disse (.+)$",
        r"^eu disse (.+)$",
        r"^corrigir para (.+)$",
        r"^nao foi (.+) foi (.+)$",
        r"^não foi (.+) foi (.+)$",
    )
    for padrao in padroes:
        m = re.match(padrao, t, flags=re.IGNORECASE)
        if m:
            grupos = m.groups()
            if len(grupos) == 2:
                return grupos[0].strip(), grupos[1].strip()  # (ouvido_errado, dito_certo)
            return None, grupos[0].strip()  # só o dito_certo
    return None
pausado = threading.Event()   # ligado = Ultron não escuta (microfone liberado)
_trava = None


# ---------- utilidades ----------
def responder(texto, confirmar, origem):
    resp = cerebro.processar(texto, confirmar, origem)
    print(f"Ultron: {resp}")
    return resp


def loop_lembretes():
    while True:
        try:
            for id_, texto in memoria.lembretes_vencidos():
                memoria.marcar_feito(id_)
                cerebro.notificar(f"Lembrete, {config.NOME}: {texto}")
        except Exception as e:
            seguranca.log.warning(f"Lembretes: {e}")
        time.sleep(5)


def atalho_falar(evento):
    """Atalho global de segurar para falar (HOTKEY_FALAR).

    A gravação acontece no laço de voz (que já tem o microfone); aqui só avisamos.
    Nunca grava com a escuta pausada.
    """
    combinacao = getattr(config, "HOTKEY_FALAR", "") or ""
    if not combinacao:
        return
    try:
        import keyboard
        # press -> começa a gravar; release -> envia o que foi dito
        keyboard.add_hotkey(combinacao, lambda: evento.set(), trigger_on_release=False)
        keyboard.add_hotkey(combinacao, lambda: evento.clear(), trigger_on_release=True)
        print(f"[segurar para falar] atalho: {combinacao}")
    except Exception as e:
        print(f"[aviso] atalho de falar indisponível: {e}")


def atalho_parada():
    try:
        import keyboard
        keyboard.add_hotkey(config.HOTKEY_PARAR, seguranca.parar_tudo)
        print(f"[parada de emergência] atalho: {config.HOTKEY_PARAR}")
    except Exception as e:
        print(f"[aviso] atalho de parada indisponível: {e}")


def preparar_windows():
    """Evita que o Windows congele ou deixe o Ultron 'sonolento' quando ele está em segundo plano."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        # 1) Desliga o QuickEdit: clicar na janela preta congelava o programa até apertar Enter
        h = k.GetStdHandle(-10)
        modo = ctypes.c_uint()
        if k.GetConsoleMode(h, ctypes.byref(modo)):
            k.SetConsoleMode(h, (modo.value | 0x80) & ~0x40)

        # 2) Desliga o "modo eficiência" (economia de energia) para este processo
        class _Estado(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
        estado = _Estado(1, 1, 0)
        k.SetProcessInformation(k.GetCurrentProcess(), 4, ctypes.byref(estado), ctypes.sizeof(estado))
    except Exception as e:
        seguranca.log.warning(f"preparar_windows: {e}")


def instancia_unica():
    global _trava
    _trava = socket.socket()
    try:
        _trava.bind(("127.0.0.1", 47653))
        return True
    except OSError:
        return False


def _arquivo_inicio():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Ultron.vbs"


def instalar_inicio():
    pyw = Path(sys.executable).with_name("pythonw.exe")
    base = Path(__file__).resolve().parent
    vbs = ('Set sh = CreateObject("WScript.Shell")\r\n'
           f'sh.CurrentDirectory = "{base}"\r\n'
           'WScript.Sleep 15000\r\n'
           f'sh.Run """{pyw}"" ""{base / "main.py"}"" --bandeja", 0, False\r\n')
    destino = _arquivo_inicio()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(vbs, encoding="utf-16")
    print(f"Pronto! O Ultron vai iniciar sozinho (em segundo plano) quando você entrar no Windows.\nArquivo: {destino}")


def remover_inicio():
    destino = _arquivo_inicio()
    if destino.exists():
        destino.unlink()
        print("Início automático removido.")
    else:
        print("O início automático não estava ativado.")


# ---------- sessão local ----------


def _desbloquear_inicial() -> bool:
    """Exige desbloqueio local antes de usar o ULTRON.

    Tenta o Windows Hello primeiro; sem sensor ou com falha, pede o PIN do .env.
    Devolve True quando a sessão fica desbloqueada, False quando não há como.
    """
    if sessao.estado().get("desbloqueada"):
        return True
    hello = biometria.disponivel() if biometria else {"disponivel": False}
    if hello.get("disponivel"):
        try:
            if biometria.verificar() is True:
                sessao.desbloquear("hello")
                print("Sessão desbloqueada pelo Windows Hello.")
                return True
        except biometria.Ocupado:
            print("Windows Hello ocupado. Use o PIN ou tente de novo.")
        except Exception:
            pass
    try:
        import seguranca
        tem_pin = bool(getattr(config, "PIN", ""))
    except Exception:
        tem_pin = False
    if tem_pin:
        pin = input("PIN de desbloqueio: ").strip()
        try:
            if seguranca.pin_valido(pin):
                sessao.desbloquear("pin")
                print("Sessão desbloqueada pelo PIN.")
                return True
        except Exception:
            pass
        print("PIN incorreto.")
    print("Sessão bloqueada. O ULTRON não pode ser usado sem desbloqueio.")
    return False


# ---------- modos ----------


def modo_texto():
    if not _desbloquear_inicial():
        return
    cerebro.NOTIFICADORES.append(lambda t: print(f"\nUltron: {t}"))
    print("Ultron em modo texto. Digite 'sair' para encerrar.")
    while True:
        try:
            t = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if t.lower() in ("sair", "exit"):
            return
        if t:
            responder(t, confirmacao.confirmar_terminal, "terminal")


def _reiniciar_audio():
    """Recarrega a lista de dispositivos de som (útil se o microfone mudou ou travou)."""
    try:
        import sounddevice as sd
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def modo_voz(bandeja=False, entrada_teclado=True, stop_event=None,
             ouvido_pronto: Callable[[object], None] | None = None,
             estado_voz: Callable[[str, str | None], None] | None = None,
             microphone_device_index=None, microphone_device_id=None,
             conversa: Callable[[str, str, str], None] | None = None,
             converter_confirmacao: Callable[[str, dict], bool] | None = None):
    def publicar_estado(estado, erro=None):
        if estado_voz is not None:
            try:
                estado_voz(estado, erro)
            except Exception:
                pass

    def responder_com_voz(comando, confirmar, origem):
        """Responde falando: com streaming, a 1ª frase toca enquanto o resto é gerado.

        Se o streaming não render nada, `finalizar()` cai no fluxo normal e a fala
        acontece depois — o comportamento anterior fica preservado.
        """
        try:
            partes, finalizar = cerebro.processar_stream(comando, confirmar, origem)
        except Exception as erro:
            seguranca.log.warning(f"Streaming indisponível ({type(erro).__name__}); modo normal.")
            texto = responder(comando, confirmar, origem)
            voz.falar(texto)
            return texto
        t0 = time.perf_counter()
        falado = voz.falar_partes(partes)
        if falado:
            # streaming funcionou: ainda precisamos gravar o histórico
            finalizar()
            seguranca.log.info(f"[tempo] 1ª frase falada em {time.perf_counter() - t0:.1f}s")
            return falado
        texto = finalizar()
        voz.falar(texto)
        return texto

    def publicar_conversa(papel, texto):
        """Leva cada fala reconhecida e cada resposta ao painel (bat-papo de voz)."""
        if conversa is None or not texto:
            return
        try:
            conversa(str(papel)[:12], str(texto)[:4000], "voz")
        except Exception:
            pass

    import voz
    import correcoes_voz
    ouvido = voz.Ouvido(device_index=microphone_device_index, device_id=microphone_device_id)
    ouvido.pausado = pausado
    falar_agora = threading.Event()   # ligado enquanto o atalho "segurar para falar" está pressionado
    ouvido.pedido_manual = falar_agora
    if ouvido_pronto is not None:
        ouvido_pronto(ouvido)
    seguranca.ganchos_parada.append(voz.parar_fala)
    cerebro.NOTIFICADORES.append(lambda t: (print(f"\nUltron: {t}"), voz.falar(t)))

    atalho_falar(falar_agora)

    confirmar_voz = confirmacao.criar_confirmador_voz(ouvido, voz)

    def digitado(texto):
        publicar_conversa("user", texto)
        resposta = responder(texto, confirmacao.confirmar_terminal, "terminal")
        publicar_conversa("assistant", resposta)
        voz.falar(resposta)

    def loop():
        calibrado, falhas, janela, device_generation = False, 0, 0.0, -1   # janela: JANELA_SEGUIMENTO sem precisar do nome após uma resposta
        pausado_reportado = False
        erro_audio = None
        ultimo_texto_usuario = None   # último reconhecimento do usuário (para correções pessoais)
        while stop_event is None or not stop_event.is_set():
            if not sessao.estado().get("desbloqueada"):
                publicar_estado("bloqueado")
                if stop_event is not None:
                    stop_event.wait(0.2)
                else:
                    time.sleep(0.2)
                continue
            if pausado.is_set():
                if not pausado_reportado:
                    publicar_estado("pausado")
                    pausado_reportado = True
                if stop_event is not None:
                    stop_event.wait(0.1)
                else:
                    time.sleep(0.1)
                continue
            pausado_reportado = False
            try:
                if ouvido.device_index == -1:
                    erro_audio = "O microfone selecionado não está disponível. Escolha uma entrada conectada."
                    publicar_estado("erro", erro_audio)
                    if stop_event is not None:
                        stop_event.wait(0.2)
                    else:
                        time.sleep(0.2)
                    continue
                if device_generation != ouvido.device_generation:
                    calibrado = False
                    device_generation = ouvido.device_generation
                if not calibrado:
                    if erro_audio is None:
                        publicar_estado("calibrando")
                    ouvido.calibrar()
                    calibrado = True
                    erro_audio = None
                    if personalidade.saudacao_ao_abrir():
                        voz.falar(personalidade.frase_saudacao())
                    print("Diga 'Ei, Ultron' seguido do comando.")
                if falar_agora.is_set() and not pausado.is_set():
                    # "segurar para falar": grava só enquanto a tecla está pressionada
                    publicar_estado("ouvindo")
                    texto = ouvido.escutar_manual()
                    if texto:
                        texto = fala.normalizar_despertar(texto)
                        publicar_conversa("user", texto)
                        publicar_estado("processando")
                        resposta = responder_com_voz(texto, confirmar_voz, "voz")
                        publicar_conversa("assistant", resposta)
                        janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 6.0)
                    continue
                if erro_audio is None:
                    publicar_estado("ouvindo")
                    # Recalibração automática do limiar: não captura eco enquanto o ULTRON fala.
                    try:
                        ouvido.recalibrar_se_necessario()
                    except Exception:
                        pass
                detalhe = ouvido.escutar_detalhado() if hasattr(ouvido, "escutar_detalhado") else {"texto": ouvido.escutar(), "alternativas": [], "erro": None}
                texto = detalhe.get("texto")
                if texto:
                    # O Whisper pode devolver "EIULTRON"/"EIUTRON"; sem isso o WAKE não acha.
                    texto = fala.normalizar_despertar(texto)
                erro_reconhecimento = detalhe.get("erro") or getattr(ouvido, "ultimo_erro", None)
                if erro_reconhecimento and str(erro_reconhecimento) == voz.ERROS.get("nao_entendi"):
                    # Só conta como "não entendi" quando houve fala e ela não foi
                    # compreendida; silêncio e falta de internet não pedem recalibração.
                    getattr(ouvido, "notificar_nao_entendido", lambda: None)()
                if erro_reconhecimento:
                    erro_audio = str(erro_reconhecimento)[:180]
                    publicar_estado("erro", erro_audio)
                else:
                    erro_audio = None
                    publicar_estado("ouvindo")
                falhas = 0
            except Exception as e:
                if stop_event is not None and stop_event.is_set():
                    break
                falhas += 1
                erro_audio = str(e)[:180]
                seguranca.log.error(f"Microfone/escuta (falha {falhas}): {e}")
                print(f"[erro de microfone] {e} - tentando de novo...")
                publicar_estado("erro", erro_audio)
                _reiniciar_audio()
                time.sleep(min(3 * falhas, 20))
                continue
            if not texto or pausado.is_set():
                continue
            # Correção pessoal: "não, eu disse X" ensina o ULTRON a trocar o que
            # ele ouviu antes pelo que o usuário realmente quis dizer.
            correcao = _detectar_correcao_pessoal(texto)
            if correcao is not None:
                ouvido_errado, dito_certo = correcao
                origem = ouvido_errado or ultimo_texto_usuario
                if origem:
                    correcoes_voz.registrar_correcao(origem, dito_certo)
                    voz.falar(f"Tudo bem. Da próxima vez entendo '{origem}' como '{dito_certo}'.", eco=0.2)
                else:
                    voz.falar("Não tenho o que corrigir ainda. Diga o comando primeiro.", eco=0.2)
                ultimo_texto_usuario = texto
                janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 6.0)
                continue
            ultimo_texto_usuario = texto
            m = WAKE.search(texto.lower())
            if m:
                cmd = texto[m.end():].strip()
                if not cmd:
                    voz.falar("Pois não?")
                    cmd = ouvido.escutar(espera=8)
                    if not cmd:
                        continue
            elif time.time() < janela:
                cmd = texto
            else:
                continue
            cmd, correcoes_pessoais = correcoes_voz.aplicar(cmd)
            cmd, correcoes_fala = fala.corrigir(cmd)
            cmd, correcoes_comando = fala.resolver_comando(cmd)
            getattr(ouvido, "notificar_comando_reconhecido", lambda: None)()
            correcoes = correcoes_pessoais + correcoes_fala + correcoes_comando
            if correcoes:
                seguranca.log.info("[fala] " + ", ".join(f"{a}->{b}" for a, b in correcoes))
            alternativas = [fala.corrigir(a)[0] for a in (detalhe.get("alternativas") or [])]
            incerteza = cerebro.interpretacao_incerta(cmd, alternativas, detalhe.get("confianca"))
            if incerteza.get("confirmar") and converter_confirmacao:
                publicar_conversa("user", cmd)
                if not converter_confirmacao(cmd, incerteza):
                    publicar_conversa("assistant", "Deixei de executar porque a fala estava ambígua.")
                    janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 6.0)
                    continue
            try:
                publicar_conversa("user", cmd)
                publicar_estado("processando")
                t_ia = time.perf_counter()
                resposta = responder_com_voz(cmd, confirmar_voz, "voz")
                seguranca.log.info(f"[tempo] IA {time.perf_counter() - t_ia:.1f}s")
                publicar_conversa("assistant", resposta)
            except Exception as e:
                seguranca.log.error(f"Erro ao responder: {e}")
            publicar_estado("ouvindo")
            janela = time.time() + getattr(config, 'JANELA_SEGUIMENTO', 6.0)
        publicar_estado("encerrado")

    if not bandeja:
        if entrada_teclado:
            threading.Thread(target=teclado.loop_digitacao, args=(digitado,), daemon=True).start()
        loop()
        return
    threading.Thread(target=loop, daemon=True).start()
    try:
        import bandeja
        bandeja.executar(pausado)       # bloqueia até escolher "Sair"
    except Exception as e:
        seguranca.log.error(f"Bandeja indisponível ({e}); rodando sem ícone.")
        while True:
            time.sleep(3600)


def rodar_testes():
    """Roda a suíte de testes localmente. Mantido fora do modo vivo para não iniciar o núcleo."""
    import shutil
    pytest = shutil.which("pytest") or str(Path(sys.executable).with_name("pytest.exe"))
    if not Path(pytest).is_file() and not shutil.which("pytest"):
        print("pytest não está instalado no ambiente. Instale com: pip install pytest")
        return 1
    return subprocess.call([str(sys.executable), "-m", "pytest", str(config.BASE / "tests"), "-q",
                            *[arg for arg in sys.argv[1:] if not arg.startswith("--testar")]])


if __name__ == "__main__":
    if "--testar" in sys.argv:
        sys.exit(rodar_testes())
    if "--instalar-inicio" in sys.argv:
        instalar_inicio()
        sys.exit(0)
    if "--remover-inicio" in sys.argv:
        remover_inicio()
        sys.exit(0)
    if not any(config.CHAVES.values()):
        print("Nenhuma chave de API no arquivo .env. Rode ULTRON-Setup.exe ou edite o .env.")
        sys.exit(1)
    somente_texto = "--texto" in sys.argv
    if not somente_texto and not instancia_unica():
        print("O Ultron já está rodando (veja o ícone perto do relógio).")
        sys.exit(0)
    preparar_windows()
    threading.Thread(target=loop_lembretes, daemon=True).start()
    atalho_parada()
    import telegram_bot
    if telegram_bot.iniciar():
        print("[telegram] bot ativo")
    try:
        if somente_texto:
            modo_texto()
        else:
            modo_voz(bandeja="--bandeja" in sys.argv)
    except KeyboardInterrupt:
        pass
    print("Ultron encerrado.")
    os._exit(0)
