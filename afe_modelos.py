"""Provisionamento e validação local dos modelos do Audio Front-End (AFE)."""
from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable

import requests

import config

PASTA_PADRAO = getattr(config, "DIR_DADOS", Path(__file__).resolve().parent / "dados") / "modelos" / "afe"

ESPECIFICACOES_MODELOS: dict[str, dict] = {
    "silero_vad": {
        "id": "silero_vad",
        "arquivo": "silero_vad.onnx",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        "sha256": "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
        "tipo": "arquivo",
        "min_bytes": 100_000,
    },
    "gtcrn": {
        "id": "gtcrn",
        "arquivo": "gtcrn_simple.onnx",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx",
        "sha256": "e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534",
        "tipo": "arquivo",
        "min_bytes": 100_000,
    },
    "vosk_pt": {
        "id": "vosk_pt",
        "arquivo": "vosk-model-small-pt-0.3",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip",
        "sha256": "6e1ce909032e1afa7a88e68a3d628ecafff302bdf195befab308826c395e93b7",
        "tipo": "zip",
        "min_bytes": 1_000_000,
    },
}

_TRAVA = threading.Lock()
_THREAD_ATIVA: threading.Thread | None = None
_ULTIMO_ERRO: str | None = None
_BAIXANDO = False


def diretorio_modelos(base_dir: Path | None = None) -> Path:
    return Path(base_dir) if base_dir is not None else PASTA_PADRAO


def _caminho_item(base: Path, spec: dict) -> Path:
    return base / spec["arquivo"]


def _item_presente(caminho: Path, spec: dict) -> bool:
    if spec.get("tipo") == "zip":
        return caminho.is_dir() and any(caminho.iterdir())
    return caminho.is_file() and caminho.stat().st_size > 0


def estado_modelos(
    base_dir: Path | None = None,
    especificacoes: dict[str, dict] | None = None,
) -> dict:
    """Devolve o estado atual dos modelos em disco sem tocar na rede."""
    base = diretorio_modelos(base_dir)
    specs = especificacoes or ESPECIFICACOES_MODELOS
    caminhos: dict[str, str] = {}
    faltando: list[str] = []
    for nome, spec in specs.items():
        alvo = _caminho_item(base, spec)
        if _item_presente(alvo, spec):
            caminhos[nome] = str(alvo)
        else:
            faltando.append(nome)
    return {
        "pronto": len(faltando) == 0,
        "baixando": _BAIXANDO,
        "faltando": faltando,
        "caminhos": caminhos,
        "erro": _ULTIMO_ERRO,
        "diretorio": str(base),
    }


def _baixar_bytes(url: str, timeout: tuple[float, float] = (5.0, 60.0)) -> bytes:
    resposta = requests.get(url, timeout=timeout, stream=True)
    resposta.raise_for_status()
    pedacos = [chunk for chunk in resposta.iter_content(chunk_size=65536) if chunk]
    return b"".join(pedacos)


def _extrair_zip_seguro(zip_path: Path, destino_dir: Path, nome_raiz: str) -> Path:
    destino_resolvido = destino_dir.resolve()
    pasta_tmp = destino_dir / f".extract_{uuid.uuid4().hex[:8]}"
    pasta_tmp.mkdir(parents=True, exist_ok=True)
    try:
        tmp_resolvido = pasta_tmp.resolve()
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                membro = Path(info.filename)
                if membro.is_absolute():
                    raise ValueError(f"caminho absoluto proibido no zip: {info.filename}")
                alvo = (tmp_resolvido / membro).resolve()
                if alvo != tmp_resolvido and not alvo.is_relative_to(tmp_resolvido):
                    raise ValueError(f"path traversal detectado no zip: {info.filename}")
                if info.is_dir():
                    alvo.mkdir(parents=True, exist_ok=True)
                else:
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info, "r") as src, open(alvo, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        raiz_extraida = pasta_tmp / nome_raiz
        origem = raiz_extraida if raiz_extraida.is_dir() else pasta_tmp
        alvo_final = destino_resolvido / nome_raiz
        if alvo_final.exists():
            shutil.rmtree(alvo_final)
        shutil.move(str(origem), str(alvo_final))
        return alvo_final
    finally:
        shutil.rmtree(pasta_tmp, ignore_errors=True)


def baixar_e_verificar_modelo(
    spec: dict,
    destino_dir: Path,
    fetcher: Callable[[str], bytes] | None = None,
) -> Path:
    """Baixa um modelo para arquivo temporário, valida SHA-256 e move atomicamente."""
    destino_dir = Path(destino_dir)
    destino_dir.mkdir(parents=True, exist_ok=True)
    baixar = fetcher or _baixar_bytes
    dados = baixar(spec["url"])
    if not dados:
        raise ValueError(f"download vazio para {spec['id']}")
    min_bytes = int(spec.get("min_bytes") or 0)
    if fetcher is None and min_bytes and len(dados) < min_bytes:
        raise ValueError(f"tamanho inesperado para {spec['id']}: {len(dados)} bytes")

    esperado = spec.get("sha256")
    if esperado:
        obtido = hashlib.sha256(dados).hexdigest().lower()
        if obtido != str(esperado).lower():
            raise ValueError(f"SHA-256 inválido para {spec['id']}")

    if spec.get("tipo") == "zip":
        tmp_zip = destino_dir / f"{spec['arquivo']}.{uuid.uuid4().hex[:8]}.zip.tmp"
        try:
            tmp_zip.write_bytes(dados)
            return _extrair_zip_seguro(tmp_zip, destino_dir, spec["arquivo"])
        finally:
            tmp_zip.unlink(missing_ok=True)

    alvo_final = destino_dir / spec["arquivo"]
    tmp_arq = destino_dir / f"{spec['arquivo']}.tmp"
    try:
        tmp_arq.write_bytes(dados)
        tmp_arq.replace(alvo_final)
        return alvo_final
    except Exception:
        tmp_arq.unlink(missing_ok=True)
        raise


def garantir_modelos_em_segundo_plano(
    base_dir: Path | None = None,
    ao_concluir: Callable[[dict], None] | None = None,
    especificacoes: dict[str, dict] | None = None,
    fetcher: Callable[[str], bytes] | None = None,
) -> threading.Thread | None:
    """Dispara download dos modelos faltantes em background sem bloquear quem chama."""
    global _THREAD_ATIVA, _ULTIMO_ERRO, _BAIXANDO
    specs = especificacoes or ESPECIFICACOES_MODELOS
    base = diretorio_modelos(base_dir)

    atual = estado_modelos(base, specs)
    if atual["pronto"]:
        if ao_concluir:
            ao_concluir(atual)
        return None

    with _TRAVA:
        if _THREAD_ATIVA is not None and _THREAD_ATIVA.is_alive():
            return _THREAD_ATIVA
        _BAIXANDO = True
        _ULTIMO_ERRO = None

        def _worker():
            global _BAIXANDO, _ULTIMO_ERRO
            try:
                for nome in atual["faltando"]:
                    spec = specs[nome]
                    if _item_presente(_caminho_item(base, spec), spec):
                        continue
                    baixar_e_verificar_modelo(spec, base, fetcher=fetcher)
                _ULTIMO_ERRO = None
            except Exception as erro:
                _ULTIMO_ERRO = f"{type(erro).__name__}: {erro}"[:180]
            finally:
                _BAIXANDO = False
                final = estado_modelos(base, specs)
                if ao_concluir:
                    try:
                        ao_concluir(final)
                    except Exception:
                        pass

        th = threading.Thread(target=_worker, name="ultron-afe-modelos", daemon=True)
        _THREAD_ATIVA = th
        th.start()
        return th
