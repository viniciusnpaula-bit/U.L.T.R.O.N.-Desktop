"""Gerenciador de tarefas longas executadas por subagentes em segundo plano.

Princípios:
- Retorno imediato (<50 ms) com `task_id` para não bloquear o turno de voz/texto.
- Progresso real (etapas observadas), nunca porcentagens simuladas.
- Cancelamento instantâneo via `cancelar(task_id)` ou `seguranca.parar_tudo()`.
- Relatórios salvos localmente em `config.DIR_RELATORIOS` com redação de segredos.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import agentes
import config
import seguranca

_TASK_ID_RE = re.compile(r"^[a-f0-9]{12}$")


class GerenciadorTarefas:
    """Coordena subagentes em background com limite de concorrência e observabilidade real."""

    def __init__(
        self,
        *,
        max_concorrentes: int = 2,
        max_historico: int = 20,
        dir_relatorios: Path | None = None,
        executor_perfil: Callable | None = None,
        notificador: Callable[[str], None] | None = None,
        publicar_palco: Callable[[str, str], None] | None = None,
    ):
        self._max_concorrentes = max(1, int(max_concorrentes))
        self._max_historico = max(5, int(max_historico))
        self._dir_relatorios = dir_relatorios
        self._executor_perfil = executor_perfil or agentes.executar_perfil
        self._notificador = notificador
        self._publicar_palco = publicar_palco

        self._lock = threading.RLock()
        self._tarefas: dict[str, dict] = {}
        self._ordem: list[str] = []
        self._canceladores: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._ouvintes: list[Callable[[dict], None]] = []

    def _pasta_relatorios(self) -> Path:
        if self._dir_relatorios is not None:
            return self._dir_relatorios
        return getattr(config, "DIR_RELATORIOS", getattr(config, "DIR_DADOS", config.BASE / "dados") / "relatorios")

    def registrar_ouvinte(self, cb: Callable[[dict], None]) -> None:
        if not callable(cb):
            return
        with self._lock:
            if cb not in self._ouvintes:
                self._ouvintes.append(cb)

    def remover_ouvinte(self, cb: Callable[[dict], None]) -> None:
        with self._lock:
            if cb in self._ouvintes:
                self._ouvintes.remove(cb)

    @staticmethod
    def _publico(item: dict) -> dict:
        return {
            "id": item["id"],
            "perfil": item["perfil"],
            "perfil_nome": item["perfil_nome"],
            "objetivo": item["objetivo"],
            "status": item["status"],
            "etapa": item["etapa"],
            "passo_atual": item["passo_atual"],
            "total_passos": item["total_passos"],
            "criado_em": item["criado_em"],
            "atualizado_em": item["atualizado_em"],
            "concluido_em": item["concluido_em"],
            "resumo": item["resumo"],
            "erro": item["erro"],
            "fontes_count": item["fontes_count"],
            "tem_relatorio": bool(item.get("relatorio_arquivo")),
        }

    def _emitir(self, item: dict) -> None:
        snap = self._publico(item)
        with self._lock:
            ouvintes = list(self._ouvintes)
        for cb in ouvintes:
            try:
                cb(snap)
            except Exception:
                pass

    def _notificar(self, texto: str) -> None:
        if not texto:
            return
        if callable(self._notificador):
            try:
                self._notificador(texto)
            except Exception:
                pass
            return
        try:
            import cerebro
            cerebro.notificar(texto)
        except Exception:
            pass

    def _enviar_ao_palco(self, titulo: str, markdown: str) -> None:
        if callable(self._publicar_palco):
            try:
                self._publicar_palco(titulo, markdown)
            except Exception:
                pass
            return
        try:
            import palco
            palco.mostrar("texto", markdown, titulo=titulo)
        except Exception:
            pass

    def _salvar_relatorio(self, task_id: str, markdown: str) -> str | None:
        if not markdown:
            return None
        try:
            pasta = self._pasta_relatorios()
            pasta.mkdir(parents=True, exist_ok=True)
            seguro = seguranca.redigir(markdown)
            destino = pasta / f"{task_id}.md"
            tmp = destino.with_suffix(".tmp")
            tmp.write_text(seguro, encoding="utf-8")
            os.replace(tmp, destino)
            return str(destino)
        except Exception:
            return None

    def _podar_historico(self) -> None:
        while len(self._ordem) > self._max_historico:
            candidato = next(
                (tid for tid in self._ordem if self._tarefas.get(tid, {}).get("status") not in ("na_fila", "executando")),
                None,
            )
            if candidato is None:
                break
            self._ordem.remove(candidato)
            self._tarefas.pop(candidato, None)
            self._canceladores.pop(candidato, None)
            self._threads.pop(candidato, None)

    def ativas_count(self) -> int:
        with self._lock:
            return sum(
                1 for item in self._tarefas.values()
                if item["status"] in ("na_fila", "executando")
            )

    def iniciar(
        self,
        objetivo: str,
        *,
        perfil: str = "pesquisador",
        abrir_palco: bool = True,
        origem: str = "desktop",
    ) -> dict:
        chave_perfil = str(perfil or "pesquisador").strip().lower()
        spec = agentes.PERFIS.get(chave_perfil)
        if spec is None:
            raise ValueError(f"Perfil de subagente desconhecido: {perfil}")
        obj = str(objetivo or "").strip()
        if not obj:
            raise ValueError("O objetivo da tarefa não pode estar vazio.")
        obj_seguro = seguranca.redigir(obj)[:300]

        with self._lock:
            if self.ativas_count() >= self._max_concorrentes:
                raise RuntimeError(
                    f"Limite de {self._max_concorrentes} tarefa(s) em segundo plano atingido. "
                    "Aguarde ou cancele uma tarefa antes de iniciar outra."
                )
            task_id = uuid.uuid4().hex[:12]
            agora = time.time()
            cancel_ev = threading.Event()
            item = {
                "id": task_id,
                "perfil": spec.id,
                "perfil_nome": spec.nome,
                "objetivo": obj_seguro,
                "status": "executando",
                "etapa": "Iniciando subagente",
                "passo_atual": 0,
                "total_passos": 4 if spec.id == "pesquisador" else spec.max_passos,
                "criado_em": agora,
                "atualizado_em": agora,
                "concluido_em": None,
                "resumo": "",
                "erro": None,
                "fontes_count": 0,
                "relatorio_arquivo": None,
                "relatorio_md": "",
                "origem": str(origem)[:24],
            }
            self._tarefas[task_id] = item
            self._ordem.append(task_id)
            self._canceladores[task_id] = cancel_ev
            self._podar_historico()

            t = threading.Thread(
                target=self._executar_worker,
                args=(task_id, spec.id, obj, cancel_ev, bool(abrir_palco)),
                name=f"ultron-subagente-{task_id}",
                daemon=True,
            )
            self._threads[task_id] = t
            self._emitir(item)
            t.start()
            return self._publico(item)

    def _executar_worker(
        self,
        task_id: str,
        perfil_id: str,
        objetivo: str,
        cancel_ev: threading.Event,
        abrir_palco: bool,
    ) -> None:
        def _progresso(etapa: str, atual: int, total: int) -> None:
            with self._lock:
                item = self._tarefas.get(task_id)
                if item is None or item["status"] != "executando":
                    return
                item["etapa"] = etapa
                item["passo_atual"] = atual
                item["total_passos"] = max(1, total)
                item["atualizado_em"] = time.time()
            self._emitir(item)

        try:
            resultado = self._executor_perfil(
                perfil_id,
                objetivo,
                progresso_cb=_progresso,
                cancel_event=cancel_ev,
            )
            cancelada = bool(cancel_ev.is_set() or (isinstance(resultado, dict) and resultado.get("cancelada")))
            if cancelada:
                with self._lock:
                    item = self._tarefas.get(task_id)
                    if item is not None:
                        item["status"] = "cancelada"
                        item["etapa"] = "Cancelada"
                        item["concluido_em"] = time.time()
                        item["atualizado_em"] = item["concluido_em"]
                        self._emitir(item)
                return

            resumo = seguranca.redigir(str((resultado or {}).get("resumo") or "Tarefa concluída."))[:500]
            relatorio_md = str((resultado or {}).get("relatorio_md") or "").strip()
            fontes = list((resultado or {}).get("fontes") or [])
            arquivo = self._salvar_relatorio(task_id, relatorio_md)

            with self._lock:
                item = self._tarefas.get(task_id)
                if item is None:
                    return
                item["status"] = "concluida"
                item["etapa"] = "Concluída"
                item["passo_atual"] = item["total_passos"]
                item["resumo"] = resumo
                item["fontes_count"] = len(fontes)
                item["relatorio_arquivo"] = arquivo
                item["relatorio_md"] = seguranca.redigir(relatorio_md)[:18000] if relatorio_md else ""
                item["concluido_em"] = time.time()
                item["atualizado_em"] = item["concluido_em"]
                snap = self._publico(item)
            self._emitir(item)

            if abrir_palco and relatorio_md:
                titulo_palco = f"{snap['perfil_nome']}: {snap['objetivo'][:60]}"
                self._enviar_ao_palco(titulo_palco, item["relatorio_md"])
            self._notificar(f"{snap['perfil_nome']} concluída. {resumo}")
        except Exception as erro:
            msg_erro = seguranca.redigir(f"{type(erro).__name__}: {erro}")[:180]
            with self._lock:
                item = self._tarefas.get(task_id)
                if item is None:
                    return
                item["status"] = "cancelada" if cancel_ev.is_set() else "erro"
                item["etapa"] = "Cancelada" if cancel_ev.is_set() else "Falha na execução"
                item["erro"] = None if cancel_ev.is_set() else msg_erro
                item["concluido_em"] = time.time()
                item["atualizado_em"] = item["concluido_em"]
                snap = self._publico(item)
            self._emitir(item)
            if snap["status"] == "erro":
                self._notificar(f"A tarefa '{snap['objetivo'][:60]}' falhou.")

    def listar(self) -> list[dict]:
        with self._lock:
            return [
                self._publico(self._tarefas[tid])
                for tid in reversed(self._ordem)
                if tid in self._tarefas
            ]

    def obter(self, task_id: str, incluir_relatorio: bool = False) -> dict | None:
        if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id.strip()):
            return None
        with self._lock:
            item = self._tarefas.get(task_id.strip())
            if item is None:
                return None
            dados = self._publico(item)
            if incluir_relatorio:
                dados["relatorio_md"] = item.get("relatorio_md") or ""
            return dados

    def cancelar(self, task_id: str) -> dict:
        if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id.strip()):
            raise ValueError("Identificador de tarefa inválido.")
        tid = task_id.strip()
        with self._lock:
            item = self._tarefas.get(tid)
            if item is None:
                raise LookupError(tid)
            cancel_ev = self._canceladores.get(tid)
            if cancel_ev is not None:
                cancel_ev.set()
            if item["status"] in ("na_fila", "executando"):
                item["status"] = "cancelada"
                item["etapa"] = "Cancelada pelo usuário"
                item["concluido_em"] = time.time()
                item["atualizado_em"] = item["concluido_em"]
                self._emitir(item)
            return self._publico(item)

    def cancelar_todas(self) -> int:
        canceladas = 0
        with self._lock:
            for tid, item in self._tarefas.items():
                if item["status"] in ("na_fila", "executando"):
                    ev = self._canceladores.get(tid)
                    if ev is not None:
                        ev.set()
                    item["status"] = "cancelada"
                    item["etapa"] = "Cancelada pela parada de emergência"
                    item["concluido_em"] = time.time()
                    item["atualizado_em"] = item["concluido_em"]
                    self._emitir(item)
                    canceladas += 1
        return canceladas


_GERENCIADOR = GerenciadorTarefas()


def _gancho_parada_tarefas() -> None:
    _GERENCIADOR.cancelar_todas()


if _gancho_parada_tarefas not in seguranca.ganchos_parada:
    seguranca.ganchos_parada.append(_gancho_parada_tarefas)


def gerenciador() -> GerenciadorTarefas:
    return _GERENCIADOR


def iniciar(objetivo: str, *, perfil: str = "pesquisador", abrir_palco: bool = True, origem: str = "desktop") -> dict:
    return _GERENCIADOR.iniciar(objetivo, perfil=perfil, abrir_palco=abrir_palco, origem=origem)


def listar() -> list[dict]:
    return _GERENCIADOR.listar()


def obter(task_id: str, incluir_relatorio: bool = False) -> dict | None:
    return _GERENCIADOR.obter(task_id, incluir_relatorio=incluir_relatorio)


def cancelar(task_id: str) -> dict:
    return _GERENCIADOR.cancelar(task_id)


def cancelar_todas() -> int:
    return _GERENCIADOR.cancelar_todas()


def ativas_count() -> int:
    return _GERENCIADOR.ativas_count()


def registrar_ouvinte(cb: Callable[[dict], None]) -> None:
    _GERENCIADOR.registrar_ouvinte(cb)


def remover_ouvinte(cb: Callable[[dict], None]) -> None:
    _GERENCIADOR.remover_ouvinte(cb)
