"""vigilancia_processos.py: Worker em segundo plano para automações do Bloco 2.

Monitora processos travados, temperaturas, janela ativa, abas pesadas e startup.
Só executa ações quando Modo Admin Operacional estiver ativo e a sessão desbloqueada.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import processos_ops
import seguranca

_log = logging.getLogger("ultron.vigilancia_processos")


class VigilanciaProcessos:
    """Worker de monitoramento contínuo em background para processos e hardware."""

    def __init__(self):
        self._parar_evento = threading.Event()
        self._thread: threading.Thread | None = None
        self._ultimo_tick_travados = 0.0
        self._ultimo_tick_termica = 0.0
        self._ultimo_tick_janela = 0.0
        self._ultimo_tick_energia = 0.0
        self._ultimo_tick_abas = 0.0
        self._ultimo_tick_startup = 0.0
        self._ultimo_tick_bluetooth = 0.0
        self._ultimo_tick_ram = 0.0
        self._ultimo_relatorio = ""

    @property
    def ativo(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._parar_evento.is_set()

    def iniciar(self):
        """Inicia a thread de vigilância."""
        if self.ativo:
            return
        self._parar_evento.clear()
        self._thread = threading.Thread(target=self._loop, name="ultron-bloco2-watcher", daemon=True)
        self._thread.start()
        _log.info("Vigilância de processos do Bloco 2 iniciada.")

    def parar(self):
        """Para a thread de vigilância com encerramento seguro."""
        self._parar_evento.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        _log.info("Vigilância de processos do Bloco 2 parada.")

    def status(self) -> dict[str, Any]:
        return {
            "ativo": self.ativo,
            "ultimo_tick_travados": self._ultimo_tick_travados,
            "ultimo_tick_termica": self._ultimo_tick_termica,
            "ultimo_tick_janela": self._ultimo_tick_janela,
            "ultimo_tick_energia": self._ultimo_tick_energia,
            "ultimo_tick_abas": self._ultimo_tick_abas,
            "ultimo_tick_startup": self._ultimo_tick_startup,
            "ultimo_tick_bluetooth": self._ultimo_tick_bluetooth,
            "ultimo_tick_ram": self._ultimo_tick_ram,
            "ultimo_relatorio": self._ultimo_relatorio,
        }

    def _executar_rotina_travados(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("matar_travados_ativo"):
            return
        try:
            res = processos_ops.encerrar_processos_travados(matar=True)
            if res.get("encerrados", 0) > 0:
                self._ultimo_relatorio = f"Processos travados encerrados: {res['encerrados']}"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de travados: %s", e)

    def _executar_rotina_termica(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("protecao_termica_ativo"):
            return
        try:
            limite = cfg.get("protecao_termica_limite_celsius", 82)
            res = processos_ops.proteger_temperatura(limite_celsius=limite, simular=False)
            if res.get("risco_throttling") and res.get("processos_limitados", 0) > 0:
                self._ultimo_relatorio = f"Alívio térmico aplicado ({res['temperatura']}°C): {res['processos_limitados']} processos contidos"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina térmica: %s", e)

    def _executar_rotina_janela_ativa(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("otimizar_janela_ativa_ativo"):
            return
        try:
            res = processos_ops.otimizar_janela_ativa(aplicar=True)
            if res.get("sucesso") and not res.get("ignorado") and res.get("restaurado_anterior"):
                _log.debug("Janela ativa priorizada: PID %s (%s)", res.get("pid_ativo"), res.get("exe"))
        except Exception as e:
            _log.warning("Erro na rotina de janela ativa: %s", e)

    def _executar_rotina_energia(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("plano_energia_ativo"):
            return
        try:
            modo = cfg.get("plano_energia_modo", "auto")
            res = processos_ops.gerenciar_plano_energia(modo=modo)
            if res.get("gatilhos"):
                self._ultimo_relatorio = f"Plano de energia ajustado ({res['modo']}): {', '.join(res['gatilhos'])}"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de energia: %s", e)

    def _executar_rotina_abas(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("suspensao_abas_ativo"):
            return
        try:
            limite = cfg.get("suspensao_abas_limite_mb", 500)
            res = processos_ops.suspender_abas_pesadas(limite_mb=limite, simular=False)
            if res.get("suspensos", 0) > 0:
                self._ultimo_relatorio = f"Abas pesadas suspensas: {res['suspensos']} ({res['mb_economizados']} MB liberados)"
                _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de abas: %s", e)

    def _executar_rotina_ram(self, cfg: dict[str, Any] | None = None):
        if not seguranca.modo_admin_ativo("bloco2"):
            return
        cfg = processos_ops.carregar_config_bloco2() if cfg is None else cfg
        if not cfg.get("limpar_ram_ativo"):
            return
        try:
            limite_pct = cfg.get("limpar_ram_limite_pct", 85)
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent >= limite_pct:
                res = processos_ops.limpar_ram_ociosa(agressivo=False)
                if res.get("mb_liberados", 0) > 50:
                    self._ultimo_relatorio = f"RAM purgada por alta utilização ({mem.percent}%): {res['mb_liberados']} MB liberados"
                    _log.info(self._ultimo_relatorio)
        except Exception as e:
            _log.warning("Erro na rotina de RAM: %s", e)

    def _loop(self):
        """Loop principal do worker com leitura única de config e espera adaptativa."""
        while not self._parar_evento.is_set():
            if not seguranca.modo_admin_ativo("bloco2"):
                self._parar_evento.wait(timeout=5.0)
                continue

            agora = time.time()
            cfg = processos_ops.carregar_config_bloco2()

            # 1. Janela ativa (a cada 4s)
            if agora - self._ultimo_tick_janela >= 4.0:
                self._executar_rotina_janela_ativa(cfg)
                self._ultimo_tick_janela = agora

            # 2. Térmica (a cada 15s)
            if agora - self._ultimo_tick_termica >= 15.0:
                self._executar_rotina_termica(cfg)
                self._ultimo_tick_termica = agora

            # 3. Energia (a cada 15s)
            if agora - self._ultimo_tick_energia >= 15.0:
                self._executar_rotina_energia(cfg)
                self._ultimo_tick_energia = agora

            # 4. Processos travados (a cada 20s)
            if agora - self._ultimo_tick_travados >= 20.0:
                self._executar_rotina_travados(cfg)
                self._ultimo_tick_travados = agora

            # 5. Abas e RAM (a cada 60s)
            if agora - self._ultimo_tick_abas >= 60.0:
                self._executar_rotina_abas(cfg)
                self._ultimo_tick_abas = agora

            if agora - self._ultimo_tick_ram >= 60.0:
                self._executar_rotina_ram(cfg)
                self._ultimo_tick_ram = agora

            restantes = [
                max(2.0, 4.0 - (agora - self._ultimo_tick_janela)),
                max(2.0, 15.0 - (agora - self._ultimo_tick_termica)),
                max(2.0, 15.0 - (agora - self._ultimo_tick_energia)),
                max(2.0, 20.0 - (agora - self._ultimo_tick_travados)),
                max(2.0, 60.0 - (agora - self._ultimo_tick_abas)),
                max(2.0, 60.0 - (agora - self._ultimo_tick_ram)),
            ]
            self._parar_evento.wait(timeout=min(15.0, min(restantes)))
