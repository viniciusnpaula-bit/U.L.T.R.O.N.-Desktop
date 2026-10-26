"""Visão computacional do ULTRON: webcam, detecção de objetos e gestos da mão.

Tudo roda localmente, sem nuvem. As bibliotecas são opcionais: quando falta
opencv, as funções devolvem um erro claro em vez de quebrar o programa.

Segurança:
  * Cada ferramenta que usa a webcam pede confirmação (risco ALTO).
  * As fotos ficam em dados/webcams/ e não saem do computador.
  * Nada aqui abre a câmera em segundo plano: só durante a chamada.
"""
from __future__ import annotations

import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
WEBCAMS_DIR = RAIZ / "dados" / "webcams"

# Limites de sanidade: nada de vídeo infinito nem foto de 8K na memória.
_MAX_SEGUNDOS = 30.0
_MAX_OBJETOS = 20
_AREA_MINIMA = 1200
_LARGURA_MAXIMA = 960


def _cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception:
        return None


def _np():
    try:
        import numpy as np  # type: ignore
        return np
    except Exception:
        return None


def _garantir_pasta_webcams() -> None:
    WEBCAMS_DIR.mkdir(parents=True, exist_ok=True)


def _abrir_camera(cv2):
    """Abre a câmera padrão no Windows sem travar: DirectShow + timeout curto."""
    try:
        captura = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    except Exception:
        captura = cv2.VideoCapture(0)
    try:
        captura.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000)
        captura.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000)
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    except Exception:
        pass
    return captura


def camera_disponivel() -> tuple[bool, str]:
    """Diz se há câmera acessível. Abre e fecha na hora, sem gravar nada."""
    cv2 = _cv2()
    if cv2 is None:
        return False, "Falta a biblioteca opencv-python (grátis) para usar a webcam."
    captura = None
    try:
        captura = _abrir_camera(cv2)
        ok = bool(captura and captura.isOpened())
        return (True, "") if ok else (False, "Nenhuma câmera acessível neste PC.")
    except Exception:
        return False, "Nenhuma câmera acessível neste PC."
    finally:
        try:
            if captura is not None:
                captura.release()
        except Exception:
            pass


def _ler_frame(captura):
    """Lê um quadro; tenta algumas vezes porque a primeira leitura costuma vir vazia."""
    for _ in range(6):
        try:
            ok, frame = captura.read()
        except Exception:
            return None
        if ok and frame is not None and getattr(frame, "size", 0):
            return frame
        time.sleep(0.12)
    return None


def _reduzir(cv2, frame):
    altura, largura = frame.shape[:2]
    if largura <= _LARGURA_MAXIMA:
        return frame
    escala = _LARGURA_MAXIMA / float(largura)
    return cv2.resize(frame, (_LARGURA_MAXIMA, int(altura * escala)), interpolation=cv2.INTER_AREA)


def _salvar_imagem(cv2, caminho: Path, frame) -> bool:
    """Grava JPEG funcionando com acentos no caminho (cv2.imwrite falha em 'Nunã')."""
    try:
        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            return False
        caminho.write_bytes(buffer.tobytes())
        return True
    except Exception:
        return False


def _ler_imagem(cv2, caminho: Path):
    np = _np()
    if np is None:
        return None
    try:
        dados = np.fromfile(str(caminho), dtype=np.uint8)
        if dados.size == 0:
            return None
        return cv2.imdecode(dados, cv2.IMREAD_COLOR)
    except Exception:
        return None


def webcam_foto() -> dict:
    """Tira uma foto da webcam e salva em dados/webcams/. Devolve o caminho."""
    cv2 = _cv2()
    if cv2 is None:
        return {"ok": False, "erro": "opencv-python não está instalado."}

    captura = None
    try:
        captura = _abrir_camera(cv2)
        if not captura or not captura.isOpened():
            return {"ok": False, "erro": "Nenhuma câmera acessível neste PC."}
        frame = _ler_frame(captura)
    finally:
        try:
            if captura is not None:
                captura.release()
        except Exception:
            pass

    if frame is None:
        return {"ok": False, "erro": "A câmera abriu, mas não entregou imagem."}

    _garantir_pasta_webcams()
    nome = f"webcam-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    caminho = WEBCAMS_DIR / nome
    if not _salvar_imagem(cv2, caminho, _reduzir(cv2, frame)):
        return {"ok": False, "erro": "Não consegui gravar a foto da webcam."}
    return {"ok": True, "arquivo": str(caminho), "nome": nome}


def _formato(cv2, contorno) -> str:
    """Classificação grosseira da silhueta: retângulo, círculo, triângulo ou forma livre."""
    perimetro = cv2.arcLength(contorno, True)
    if perimetro <= 0:
        return "forma"
    aprox = cv2.approxPolyDP(contorno, 0.035 * perimetro, True)
    lados = len(aprox)
    if lados == 3:
        return "triângulo"
    if lados == 4:
        return "retângulo"
    if lados > 7:
        return "círculo"
    return "forma livre"


def detectar_objetos(caminho_imagem: str | None = None) -> dict:
    """Detecta objetos (formas) numa imagem local.

    Se caminho_imagem for None, tira uma foto da webcam primeiro. Usa contornos
    do OpenCV: rápido, offline e sem enviar imagem para lugar nenhum.
    """
    cv2 = _cv2()
    if cv2 is None:
        return {"ok": False, "erro": "opencv-python não está instalado."}

    if not caminho_imagem:
        foto = webcam_foto()
        if not foto.get("ok"):
            return foto
        caminho_imagem = foto["arquivo"]

    caminho = Path(str(caminho_imagem)).expanduser()
    if not caminho.is_absolute():
        caminho = (RAIZ / caminho).resolve()
    if not caminho.is_file():
        return {"ok": False, "erro": f"Imagem não encontrada: {caminho}"}

    img = _ler_imagem(cv2, caminho)
    if img is None:
        return {"ok": False, "erro": f"Não consegui ler a imagem: {caminho}"}

    img = _reduzir(cv2, img)
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cinza = cv2.GaussianBlur(cinza, (5, 5), 0)
    bordas = cv2.Canny(cinza, 50, 150)
    bordas = cv2.dilate(bordas, None, iterations=1)
    contornos, _ = cv2.findContours(bordas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    altura, largura = img.shape[:2]
    objetos = []
    for contorno in contornos:
        area = float(cv2.contourArea(contorno))
        if area < _AREA_MINIMA:
            continue
        x, y, w, h = cv2.boundingRect(contorno)
        objetos.append({
            "formato": _formato(cv2, contorno),
            "x": int(x), "y": int(y),
            "largura": int(w), "altura": int(h),
            "area": int(area),
            "centro": [int(x + w / 2), int(y + h / 2)],
        })

    objetos.sort(key=lambda o: o["area"], reverse=True)
    objetos = objetos[:_MAX_OBJETOS]
    return {
        "ok": True,
        "imagem": str(caminho),
        "dimensoes": {"largura": int(largura), "altura": int(altura)},
        "total": len(objetos),
        "objetos": objetos,
    }


# ---------- gestos da mão (OpenCV puro, sem modelo para baixar) ----------
def _mascara_pele(cv2, frame):
    """Isola tons de pele em YCrCb. Funciona com luz normal; não é reconhecimento facial."""
    suave = cv2.GaussianBlur(frame, (5, 5), 0)
    ycrcb = cv2.cvtColor(suave, cv2.COLOR_BGR2YCrCb)
    mascara = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, nucleo, iterations=1)
    # Fechamento mínimo: fechar demais solda os dedos e apaga os vales.
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    return mascara


def _maior_contorno(cv2, mascara):
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    return max(contornos, key=cv2.contourArea)


def _centro_palma(cv2, mascara):
    """Centro da palma = centro do maior círculo inscrito na máscara.

    O centroide do contorno não serve: numa mão ele cai perto do pulso, e a
    palma passa a "esconder" os dedos no perfil radial.
    """
    try:
        distancias = cv2.distanceTransform(mascara, cv2.DIST_L2, 5)
        _, raio, _, ponto = cv2.minMaxLoc(distancias)
        if raio and raio > 0:
            return ponto, float(raio)
    except Exception:
        pass
    return None, 0.0


def _contar_dedos(cv2, contorno, mascara) -> int:
    """Conta dedos pelo perfil radial a partir do centro da palma.

    Cada dedo esticado vira um pico de distância; punho fechado não tem picos.
    """
    np = _np()
    if np is None:
        return 0
    pontos = contorno.reshape(-1, 2).astype(float)
    if len(pontos) < 12:
        return 0
    centro, raio_palma = _centro_palma(cv2, mascara)
    if centro is None:
        return 0
    centro_x, centro_y = float(centro[0]), float(centro[1])

    dx, dy = pontos[:, 0] - centro_x, pontos[:, 1] - centro_y
    distancias = np.hypot(dx, dy)
    angulos = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0

    # 360 baldes de 1 grau; em cada direção vale o ponto mais distante.
    baldes = np.zeros(360, dtype=float)
    indices = np.clip(angulos.astype(int), 0, 359)
    np.maximum.at(baldes, indices, distancias)
    validos = baldes > 0
    if int(validos.sum()) < 20:
        return 0

    eixo = np.arange(360)
    perfil = np.interp(eixo, eixo[validos], baldes[validos], period=360)
    suave = np.convolve(np.r_[perfil[-2:], perfil, perfil[:2]], np.ones(5) / 5, mode="same")[2:-2]

    limite = max(raio_palma * 1.45, float(np.median(suave)) * 1.15)
    if float(suave.max()) < limite:
        return 0

    picos = []
    for i in range(360):
        janela = [suave[(i + k) % 360] for k in range(-6, 7)]
        if suave[i] >= limite and suave[i] == max(janela):
            picos.append(i)

    # Junta picos vizinhos (mesma ponta de dedo vista em dois baldes).
    separados: list[int] = []
    for i in picos:
        if not separados or min((i - j) % 360 for j in separados) > 8:
            separados.append(i)
    return min(len(separados), 5)


def _nome_do_gesto(dedos: int) -> str:
    if dedos <= 0:
        return "punho"
    if dedos == 1:
        return "indica"
    if dedos == 2:
        return "dois_dedos"
    if dedos == 3:
        return "tres_dedos"
    return "mao_aberta"


def _analisar_frame_mao(cv2, frame):
    """Devolve (gesto, centro_da_mao, área) para um quadro."""
    frame = _reduzir(cv2, frame)
    mascara = _mascara_pele(cv2, frame)
    contorno = _maior_contorno(cv2, mascara)
    if contorno is None:
        return "nenhum", None, 0.0
    area = float(cv2.contourArea(contorno))
    if area < 4000:  # ruído: parede, rosto pequeno, fundo bege
        return "nenhum", None, 0.0
    dedos = _contar_dedos(cv2, contorno, mascara)
    momentos = cv2.moments(contorno)
    if momentos["m00"]:
        centro = (momentos["m10"] / momentos["m00"], momentos["m01"] / momentos["m00"])
    else:
        x, y, w, h = cv2.boundingRect(contorno)
        centro = (x + w / 2, y + h / 2)
    return _nome_do_gesto(dedos), centro, area


def detectar_gestos_mao(segundos: float = 3.0) -> dict:
    """Observa a webcam por alguns segundos e devolve o gesto mais frequente.

    Gestos: punho, indica, dois_dedos, tres_dedos, mao_aberta ou nenhum.
    """
    cv2 = _cv2()
    if cv2 is None:
        return {"ok": False, "erro": "opencv-python não está instalado."}

    duracao = max(1.0, min(_MAX_SEGUNDOS, float(segundos or 3.0)))
    captura = None
    vistos: dict[str, int] = {}
    try:
        captura = _abrir_camera(cv2)
        if not captura or not captura.isOpened():
            return {"ok": False, "erro": "Nenhuma câmera acessível neste PC."}
        fim = time.time() + duracao
        while time.time() < fim:
            frame = _ler_frame(captura)
            if frame is None:
                break
            gesto, _centro, _area = _analisar_frame_mao(cv2, frame)
            vistos[gesto] = vistos.get(gesto, 0) + 1
    except Exception as e:
        return {"ok": False, "erro": f"Não consegui analisar a webcam ({type(e).__name__})."}
    finally:
        try:
            if captura is not None:
                captura.release()
        except Exception:
            pass

    if not vistos:
        return {"ok": False, "erro": "A câmera não entregou imagem."}

    # Ignora "nenhum" quando houve algum gesto de verdade.
    uteis = {g: n for g, n in vistos.items() if g != "nenhum"}
    escolhido = max(uteis or vistos, key=(uteis or vistos).get)
    total = sum(vistos.values())
    return {
        "ok": True,
        "gesto": escolhido,
        "confianca": round(vistos[escolhido] / total, 2),
        "amostras": total,
        "contagem": vistos,
    }


def controlar_mouse_com_gesto(segundos: float = 8.0) -> dict:
    """Move o ponteiro seguindo a mão enquanto o gesto for 'indica'.

    Punho fecha o controle; qualquer outro gesto pausa o movimento. Limitado a
    30 segundos e interrompido pela parada de emergência ou pelo canto da tela.
    """
    cv2 = _cv2()
    if cv2 is None:
        return {"ok": False, "erro": "opencv-python não está instalado."}

    try:
        import pyautogui
    except Exception:
        return {"ok": False, "erro": "pyautogui não está instalado."}

    import seguranca

    duracao = max(1.0, min(_MAX_SEGUNDOS, float(segundos or 8.0)))
    largura_tela, altura_tela = pyautogui.size()
    pyautogui.PAUSE = 0
    pyautogui.FAILSAFE = True

    captura = None
    movimentos = 0
    gestos: dict[str, int] = {}
    try:
        captura = _abrir_camera(cv2)
        if not captura or not captura.isOpened():
            return {"ok": False, "erro": "Nenhuma câmera acessível neste PC."}
        fim = time.time() + duracao
        while time.time() < fim:
            if seguranca.parada.is_set():
                return {"ok": False, "erro": "Parada de emergência acionada.", "movimentos": movimentos}
            frame = _ler_frame(captura)
            if frame is None:
                break
            gesto, centro, _area = _analisar_frame_mao(cv2, frame)
            gestos[gesto] = gestos.get(gesto, 0) + 1
            if gesto == "punho":
                break
            if gesto == "indica" and centro is not None:
                altura, largura = frame.shape[:2]
                # Espelha o eixo X: a mão indo para a direita move o ponteiro para a direita.
                x = (1.0 - (centro[0] / largura)) * largura_tela
                y = (centro[1] / altura) * altura_tela
                pyautogui.moveTo(
                    max(0, min(largura_tela - 1, x)),
                    max(0, min(altura_tela - 1, y)),
                    duration=0.08,
                )
                movimentos += 1
    except pyautogui.FailSafeException:
        return {"ok": False, "erro": "Controle interrompido pelo canto da tela.", "movimentos": movimentos}
    except Exception as e:
        return {"ok": False, "erro": f"Falha no controle por gesto ({type(e).__name__}).", "movimentos": movimentos}
    finally:
        try:
            if captura is not None:
                captura.release()
        except Exception:
            pass

    return {
        "ok": True,
        "movimentos": movimentos,
        "gestos": gestos,
        "segundos": duracao,
    }
