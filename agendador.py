"""Agendador único do núcleo: lembretes, agenda, fluxos agendados e briefing.

`tick()` é o passo testável; `loop()` só repete o tick a cada poucos segundos.
Fluxos agendados rodam PELO portão de ferramentas e qualquer etapa que exija
confirmação é negada (não há ninguém presente para confirmar).
"""
from __future__ import annotations

import datetime
import threading

import config


def _negar(_pedido) -> bool:
    return False


class Agendador:
    def __init__(self, notificar=None, executar_ferramenta=None, intervalo=5.0, agora=None):
        self._notificar = notificar
        self._executar = executar_ferramenta
        self.intervalo = max(0.5, float(intervalo))
        self._agora = agora or (lambda: datetime.datetime.now().timestamp())
        self._ultimo_briefing: str | None = None
        self._lock = threading.Lock()

    def _avisar(self, texto: str) -> None:
        try:
            if self._notificar is not None:
                self._notificar(str(texto))
            else:
                import cerebro
                cerebro.notificar(str(texto))
        except Exception:
            pass

    def _rodar_ferramenta(self, nome, args, confirmar, origem):
        if self._executar is not None:
            return self._executar(nome, args, confirmar, origem)
        import ferramentas
        return ferramentas.executar(nome, args, confirmar, origem)

    def _executar_evento(self, item: dict) -> None:
        import memoria
        fluxo_id = str(item.get("fluxo_id") or "")
        if fluxo_id:
            try:
                import sessao
                desbloqueada = bool(sessao.estado().get("desbloqueada"))
            except Exception:
                desbloqueada = False
            if not desbloqueada:
                self._avisar(f"Agenda: “{item['texto']}” não rodou porque a sessão está bloqueada.")
            else:
                import fluxos
                resultado = fluxos.executar(fluxo_id, self._rodar_ferramenta, _negar, "agendado")
                self._avisar(resultado.get("resumo") or item["texto"])
        else:
            self._avisar(f"Agenda, {config.NOME}: {item['texto']}")
        if item.get("repetir_minutos", 0) > 0:
            memoria.reagendar_evento(item["id"], item["repetir_minutos"], item.get("quando"))
        else:
            memoria.marcar_evento_feito(item["id"])

    def tick(self, agora=None) -> None:
        agora = self._agora() if agora is None else float(agora)
        import briefing
        import memoria

        try:
            for item in memoria.lembretes_vencidos_detalhado():
                self._avisar(f"Lembrete, {config.NOME}: {item['texto']}")
                if item.get("repetir_minutos", 0) > 0:
                    memoria.reagendar_lembrete(item["id"], item["repetir_minutos"], item.get("due"))
                else:
                    memoria.marcar_feito(item["id"])
        except Exception:
            pass

        try:
            for item in memoria.eventos_vencidos_detalhado():
                self._executar_evento(item)
        except Exception:
            pass

        quando = datetime.datetime.fromtimestamp(agora)
        if briefing.devido(quando, self._ultimo_briefing):
            with self._lock:
                if briefing.devido(quando, self._ultimo_briefing):
                    self._ultimo_briefing = quando.date().isoformat()
                    texto = briefing.compor(agora=quando, executar_ferramenta=self._executar)
                    if texto:
                        self._avisar(texto)

    def loop(self, stop_event=None) -> None:
        stop = stop_event or threading.Event()
        while not stop.wait(self.intervalo):
            self.tick()


def loop(stop_event=None) -> None:
    Agendador().loop(stop_event)
