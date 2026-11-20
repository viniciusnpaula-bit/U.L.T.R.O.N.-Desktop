"""vigilancia_disco.py: Worker em segundo plano para automações do Bloco 1.

Monitora Downloads, capturas antigas, uso de disco e unidades USB ociosas.
Só executa ações quando Modo Admin Operacional estiver ativo e a sessão desbloqueada.
"""
import logging
import threading
import time
from typing import Any

import disco_ops
import seguranca

_log = logging.getLogger("ultron.vigilancia_disco")


class VigilanciaDisco:
    """Worker de monitoramento contínuo em background para arquivos e disco."""

    def __init__(self):
        self._parar_evento = threading.Event()
        self._thread: threading.Thread | None = None
        self._ultimo_tick_downloads = 0.0
        self._ultimo_tick_prints = 0.0
        self._ultimo_tick_usb = 0.0
        self._ultimo_tick_disco = 0.0
        self._ultima_limpeza_disco = 0.0
        self._ultimo_relatorio = ""

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._parar_evento.is_set()

    def iniciar(self):
        """Inicia a thread de vigilância."""
        if self.ativo:
            return
        self._parar_evento.clear()
        self._thread = threading.Thread(target=self._loop, name="ultron-bloco1-watcher", daemon=True)
        self._thread.start()
        _log.info("Vigilância de disco do Bloco 1 iniciada.")

    def parar(self):
        """Para a thread de vigilância com encerramento seguro."""
        self._parar_evento.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        _log.info("Vigilância de disco do Bloco 1 parada.")

    def status(self) -> dict[str, Any]:
        return {
            "ativo": self.ativo,
            "ultimo_tick_downloads": self._ultimo_tick_downloads,
            "ultimo_tick_prints": self._ultimo_tick_prints,
            "ultimo_tick_usb": self._ultimo_tick_usb,
            "ultimo_tick_disco": self._ultimo_tick_disco,
            "ultima_limpeza_disco": self._ultima_limpeza_disco,
            "ultimo_relatorio": self._ultimo_relatorio,
        }

    def _executar_rotina_downloads(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco1"):
            return
        cfg = disco_ops.carregar_config_bloco1() if cfg is None else cfg
        if not cfg.get("downloads_pdf_ativo"):
            return
        try:
            res = disco_ops.organizar_pdf_downloads(aplicar=True)
            if res.get("renomeados", 0) > 0:
                self._ultimo_relatorio = f"PDFs renomeados em Downloads: {res['renomeados']}"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de downloads: %s", e)

    def _executar_rotina_prints(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco1"):
            return
        cfg = disco_ops.carregar_config_bloco1() if cfg is None else cfg
        if not cfg.get("capturas_desktop_ativo"):
            return
        try:
            dias = cfg.get("capturas_dias", 7)
            res = disco_ops.arquivar_capturas_desktop(dias=dias, executar=True)
            if res.get("movidos", 0) > 0:
                self._ultimo_relatorio = f"Capturas de tela arquivadas: {res['movidos']}"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de prints: %s", e)

    def _executar_rotina_usb(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco1"):
            return
        cfg = disco_ops.carregar_config_bloco1() if cfg is None else cfg
        if not cfg.get("usb_ejetar_ativo"):
            return
        try:
            minutos = max(1, cfg.get("usb_ocioso_seg", 300) // 60)
            res = disco_ops.ejetar_usb_ocioso(minutos_ocioso=minutos)
            ejetadas = res.get("ejetadas", [])
            if ejetadas:
                self._ultimo_relatorio = f"Unidades USB ejetadas por inatividade: {', '.join(ejetadas)}"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina USB: %s", e)

    def _executar_rotina_disco(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco1"):
            return
        cfg = disco_ops.carregar_config_bloco1() if cfg is None else cfg
        if not cfg.get("disco_alerta_ativo"):
            return
        agora = time.time()
        # Cooldown de 6 horas entre limpezas automáticas
        if agora - self._ultima_limpeza_disco < 21600:
            return
        try:
            limite = cfg.get("disco_limite_pct", 80)
            res = disco_ops.limpar_disco(executar=True, limite_pct=limite)
            if res.get("executado"):
                self._ultima_limpeza_disco = agora
                mb = res.get("caches_navegador", {}).get("bytes_liberados", 0) / (1024 * 1024)
                self._ultimo_relatorio = f"Limpeza automática executada: {mb:.1f} MB liberados em caches."
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de disco: %s", e)

    def _loop(self):
        while not self._parar_evento.is_set():
            if not seguranca.modo_admin_ativo("bloco1"):
                self._parar_evento.wait(timeout=5.0)
                continue

            agora = time.time()
            cfg = disco_ops.carregar_config_bloco1()

            # Downloads: a cada 10 s
            if agora - self._ultimo_tick_downloads >= 10:
                self._ultimo_tick_downloads = agora
                self._executar_rotina_downloads(cfg)

            # Prints: a cada 30 s
            if agora - self._ultimo_tick_prints >= 30:
                self._ultimo_tick_prints = agora
                self._executar_rotina_prints(cfg)

            # USB: a cada 15 s
            if agora - self._ultimo_tick_usb >= 15:
                self._ultimo_tick_usb = agora
                self._executar_rotina_usb(cfg)

            # Disco: a cada 300 s (5 min)
            if agora - self._ultimo_tick_disco >= 300:
                self._ultimo_tick_disco = agora
                self._executar_rotina_disco(cfg)

            restantes = [
                max(1.0, 10.0 - (agora - self._ultimo_tick_downloads)),
                max(1.0, 30.0 - (agora - self._ultimo_tick_prints)),
                max(1.0, 15.0 - (agora - self._ultimo_tick_usb)),
                max(1.0, 300.0 - (agora - self._ultimo_tick_disco)),
            ]
            self._parar_evento.wait(timeout=min(10.0, min(restantes)))
