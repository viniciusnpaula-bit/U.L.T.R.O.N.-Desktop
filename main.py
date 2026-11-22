"""ULTRON - ponto de entrada.
   python main.py                  -> modo voz com janela
   python main.py --bandeja        -> modo voz em segundo plano, com ícone na bandeja (sem janela)
   python main.py --texto          -> só terminal
   python main.py --instalar-inicio / --remover-inicio   -> iniciar junto com o Windows
   python main.py --testar                               -> testes locais (roda pytest)"""
import getpass
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
    _log_dir = getattr(config, "DIR_LOGS", config.BASE / "logs")
    Path(_log_dir).mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(Path(_log_dir) / "console.log", "a", buffering=1, encoding="utf-8")

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
    sessao.tocar()
    resp = cerebro.processar(texto, confirmar, origem)
    print(f"Ultron: {resp}")
    return resp


def loop_lembretes(stop_event=None):
    """Thread única do núcleo para lembretes, agenda, fluxos agendados e briefing."""
    import agendador
    agendador.loop(stop_event)


_hotkeys_registradas: set[str] = set()


def remover_atalhos():
    """Remove todos os atalhos globais registrados e libera os listeners."""
    global _hotkeys_registradas
    try:
        import keyboard
        keyboard.clear_all_hotkeys()
    except Exception:
        pass
    _hotkeys_registradas.clear()


def atalho_falar(evento):
    """Atalho global de segurar para falar (HOTKEY_FALAR).

    A gravação acontece no laço de voz (que já tem o microfone); aqui só avisamos.
    Nunca grava com a escuta pausada.
    """
    combinacao = getattr(config, "HOTKEY_FALAR", "") or ""
    if not combinacao:
        return
    if combinacao.strip().lower() == getattr(config, "HOTKEY_PARAR", "").strip().lower():
        print(f"[aviso] conflito: atalho de falar igual ao de parada ({combinacao}); ignorando atalho de falar.")
        return
    if "falar" in _hotkeys_registradas:
        return
    try:
        import keyboard
        # press -> começa a gravar; release -> envia o que foi dito
        keyboard.add_hotkey(combinacao, lambda: evento.set(), trigger_on_release=False)
        keyboard.add_hotkey(combinacao, lambda: evento.clear(), trigger_on_release=True)
        _hotkeys_registradas.add("falar")
        print(f"[segurar para falar] atalho: {combinacao}")
    except Exception as e:
        print(f"[aviso] atalho de falar indisponível: {e}")


def atalho_parada():
    if "parada" in _hotkeys_registradas:
        return
    try:
        import keyboard
        keyboard.add_hotkey(config.HOTKEY_PARAR, seguranca.parar_tudo)
        _hotkeys_registradas.add("parada")
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
        tem_pin = bool(seguranca.pin_configurado())
    except Exception:
        tem_pin = False
    if tem_pin:
        try:
            # getpass não ecoa os dígitos nem grava o PIN em logs/console.log.
            pin = getpass.getpass("PIN de desbloqueio: ").strip()
        except (EOFError, KeyboardInterrupt):
            return False
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


def _curar_skills() -> None:
    try:
        import skills
        resumo = skills.curar()
        print(f"skills: {resumo['ativos']} ativas, {resumo['obsoletos']} obsoletas, "
              f"{resumo['arquivados']} arquivadas, {resumo['pendentes']} pendentes")
        for aviso in resumo["avisos"]:
            print(aviso)
    except Exception:
        pass


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
             converter_confirmacao: Callable[[str, dict], bool] | None = None,
             notificar_voz: bool = True):
    def publicar_estado(estado, erro=None):
        if estado_voz is not None:
            try:
                estado_voz(estado, erro)
            except Exception:
                pass

    def _eco_atual():
        afe = getattr(ouvido, "afe", None) if "ouvido" in locals() else None
        return 0.1 if (afe is not None and getattr(afe, "aec_ativo", False)) else 0.4

    def _falar_resposta(texto, emocao="neutro"):
        if not texto:
            return
        eco = _eco_atual()
        if emocao and emocao != "neutro":
            try:
                voz.falar(texto, eco=eco, emocao=emocao)
                return
            except TypeError:
                pass
        voz.falar(texto, eco=eco)

    def responder_com_voz(comando, confirmar, origem):
        """Responde falando: com streaming, a 1ª frase toca enquanto o resto é gerado.

        Quando o modelo aciona ferramentas ou ocorre fallback no meio do stream,
        `finalizar()` conclui o ciclo normal e a resposta final é falada e
        devolvida ao painel.
        """
        sessao.tocar()
        try:
            partes, finalizar = cerebro.processar_stream(comando, confirmar, origem)
        except Exception as erro:
            seguranca.log.warning(f"Streaming indisponível ({type(erro).__name__}); modo normal.")
            texto = responder(comando, confirmar, origem)
            _falar_resposta(texto)
            return texto
        t0 = time.perf_counter()

        class _PartesAbortaveis:
            def __iter__(self_it):
                for item in partes:
                    parar_voz = getattr(voz, "_parar", None)
                    if parar_voz is not None and parar_voz.is_set():
                        break
                    yield item

            def __getattr__(self_it, nome):
                return getattr(partes, nome)

        falado = voz.falar_partes(_PartesAbortaveis(), eco=_eco_atual())
        texto = finalizar()
        if getattr(voz, "foi_interrompido", lambda: False)():
            return texto or falado
        pos_stream = bool(getattr(partes, "resposta_pos_stream", False))
        emocao = getattr(partes, "registro", None) or "neutro"
        if falado and not pos_stream:
            # streaming conversacional puro terminou sem pós-processamento
            seguranca.log.info(f"[tempo] 1ª frase falada em {time.perf_counter() - t0:.1f}s")
            return texto or falado
        print(f"Ultron: {texto}")
        _falar_resposta(texto, emocao=emocao)
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
    if hasattr(ouvido, "preparar_afe"):
        ouvido.preparar_afe()
    if ouvido_pronto is not None:
        ouvido_pronto(ouvido)
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
                        publicar_estado("aquecendo_afe")
                    if hasattr(ouvido, "iniciar_afe"):
                        ouvido.iniciar_afe()
                    if erro_audio is None:
                        publicar_estado("calibrando")
                    ouvido.calibrar()
                    calibrado = True
                    erro_audio = None
                    publicar_estado("ouvindo")
                    if personalidade.saudacao_ao_abrir():
                        # Aguarda a dissolução da tela de carregamento para falar ao revelar o núcleo.
                        if stop_event is not None:
                            stop_event.wait(0.75)
                        else:
                            time.sleep(0.75)
                        if (stop_event is None or not stop_event.is_set()) and not pausado.is_set():
                            voz.falar(personalidade.frase_saudacao(), eco=_eco_atual())
                    print(f"Diga 'Ei, {fala.nome_despertar()}' seguido do comando.")
                if falar_agora.is_set() and not pausado.is_set():
                    # "segurar para falar": grava só enquanto a tecla está pressionada
                    publicar_estado("ouvindo")
                    texto = ouvido.escutar_manual()
                    if texto:
                        texto = fala.normalizar_despertar(texto)
                        try:
                            publicar_conversa("user", texto)
                            publicar_estado("processando")
                            resposta = responder_com_voz(texto, confirmar_voz, "voz")
                            publicar_conversa("assistant", resposta)
                        except Exception as e:
                            seguranca.log.error(f"Erro ao responder: {e}")
                        publicar_estado("ouvindo")
                        janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 15.0)
                    continue
                if erro_audio is None:
                    publicar_estado("ouvindo")
                    # Recalibração automática do limiar: não captura eco enquanto o ULTRON fala.
                    try:
                        ouvido.recalibrar_se_necessario()
                    except Exception:
                        pass
                exigir_wake = time.time() >= janela
                if hasattr(ouvido, "escutar_detalhado"):
                    try:
                        detalhe = ouvido.escutar_detalhado(exigir_wake=exigir_wake)
                    except TypeError:
                        detalhe = ouvido.escutar_detalhado()
                else:
                    detalhe = {"texto": ouvido.escutar(), "alternativas": [], "erro": None}
                texto = detalhe.get("texto")
                if texto:
                    # O Whisper pode devolver "EIULTRON"/"EIUTRON"; sem isso o WAKE não acha.
                    texto = fala.normalizar_despertar(texto)
                erro_reconhecimento = detalhe.get("erro") or getattr(ouvido, "ultimo_erro", None)
                erros_voz = getattr(voz, "ERROS", {}) or {}
                if erro_reconhecimento and str(erro_reconhecimento) == erros_voz.get("nao_entendi"):
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
                janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 15.0)
                continue
            ultimo_texto_usuario = texto
            m = fala.regex_wake().search(texto.lower())
            if m:
                cmd = texto[m.end():].strip()
                if not cmd:
                    voz.falar("Pois não?", eco=_eco_atual())
                    try:
                        cmd = ouvido.escutar(espera=8, exigir_wake=False)
                    except TypeError:
                        cmd = ouvido.escutar(espera=8)
                    if not cmd:
                        continue
            elif detalhe.get("wake_detectado") or time.time() < janela:
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
                    janela = time.time() + getattr(config, "JANELA_SEGUIMENTO", 15.0)
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
            janela = time.time() + getattr(config, 'JANELA_SEGUIMENTO', 15.0)
        publicar_estado("encerrado")

    _gancho_parada = voz.parar_fala
    _notificador_voz = None
    seguranca.ganchos_parada.append(_gancho_parada)
    if notificar_voz:
        def _notificar_voz(texto_aviso):
            print(f"\nUltron: {texto_aviso}")
            if (not getattr(config, "VOZ_ATIVO", True)
                    or not getattr(config, "VOZ_NOTIFICACOES", True)
                    or pausado.is_set()
                    or (getattr(seguranca, "parada", None) and seguranca.parada.is_set())):
                return
            try:
                voz.falar(texto_aviso)
            except Exception as erro_voz:
                seguranca.log.warning(f"Voz da notificação falhou: {type(erro_voz).__name__}")

        _notificador_voz = _notificar_voz
        cerebro.NOTIFICADORES.append(_notificador_voz)

    try:
        if not bandeja:
            if entrada_teclado:
                threading.Thread(target=teclado.loop_digitacao, args=(digitado,), daemon=True).start()
            loop()
            return
        threading.Thread(target=loop, daemon=True).start()
        try:
            import bandeja
            bandeja.executar(pausado)       # bloqueia até escolher "Sair"
            if stop_event is not None:
                stop_event.set()
        except Exception as e:
            seguranca.log.error(f"Bandeja indisponível ({e}); rodando sem ícone.")
            while stop_event is None or not stop_event.is_set():
                if stop_event is not None:
                    stop_event.wait(3600)
                else:
                    time.sleep(3600)
    finally:
        if hasattr(ouvido, "parar_afe"):
            try:
                ouvido.parar_afe()
            except Exception:
                pass
        if stop_event is not None:
            stop_event.set()
        remover_atalhos()
        if _gancho_parada in seguranca.ganchos_parada:
            seguranca.ganchos_parada.remove(_gancho_parada)
        if _notificador_voz is not None and _notificador_voz in cerebro.NOTIFICADORES:
            cerebro.NOTIFICADORES.remove(_notificador_voz)


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
    _curar_skills()
    threading.Thread(target=loop_lembretes, daemon=True).start()
    try:
        import vigilancia_disco
        _vig_disco = vigilancia_disco.VigilanciaDisco()
        _vig_disco.iniciar()
    except Exception as _e_vig:
        seguranca.log.warning("Falha ao iniciar vigilancia_disco: %s", _e_vig)
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
