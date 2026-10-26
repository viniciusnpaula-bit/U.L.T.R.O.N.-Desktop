import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import visao

TEM_CV2 = visao._cv2() is not None and visao._np() is not None


def _imagem(caminho: Path, desenhar, fundo=(20, 20, 20)) -> Path:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 480), fundo)
    desenhar(ImageDraw.Draw(img))
    img.save(caminho)
    return caminho


def _frame(caminho: Path):
    import cv2
    import numpy as np
    from PIL import Image
    return cv2.cvtColor(np.array(Image.open(caminho)), cv2.COLOR_RGB2BGR)


PELE = (224, 172, 140)


def _mao_aberta(d):
    d.rounded_rectangle((230, 250, 410, 430), radius=30, fill=PELE)
    for x in (245, 295, 345, 395):
        d.rounded_rectangle((x - 18, 90, x + 18, 280), radius=16, fill=PELE)
    d.rounded_rectangle((180, 300, 250, 345), radius=20, fill=PELE)


def _punho(d):
    d.rounded_rectangle((230, 220, 410, 400), radius=45, fill=PELE)


def _um_dedo(d):
    d.rounded_rectangle((250, 260, 410, 430), radius=30, fill=PELE)
    d.rounded_rectangle((310, 90, 350, 300), radius=18, fill=PELE)


class NomeDoGestoTestes(unittest.TestCase):
    def test_mapa_de_dedos_para_gestos(self):
        self.assertEqual(visao._nome_do_gesto(0), "punho")
        self.assertEqual(visao._nome_do_gesto(1), "indica")
        self.assertEqual(visao._nome_do_gesto(2), "dois_dedos")
        self.assertEqual(visao._nome_do_gesto(3), "tres_dedos")
        self.assertEqual(visao._nome_do_gesto(4), "mao_aberta")
        self.assertEqual(visao._nome_do_gesto(5), "mao_aberta")


@unittest.skipUnless(TEM_CV2, "opencv-python não instalado")
class GestosTestes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def _gesto(self, desenhar) -> str:
        caminho = _imagem(self.base / "mao.png", desenhar)
        return visao._analisar_frame_mao(visao._cv2(), _frame(caminho))[0]

    def test_mao_aberta(self):
        self.assertEqual(self._gesto(_mao_aberta), "mao_aberta")

    def test_punho(self):
        self.assertEqual(self._gesto(_punho), "punho")

    def test_um_dedo(self):
        self.assertEqual(self._gesto(_um_dedo), "indica")

    def test_fundo_sem_pele_nao_detecta_mao(self):
        self.assertEqual(self._gesto(lambda d: d.rectangle((0, 0, 10, 10), fill=(0, 0, 0))), "nenhum")


@unittest.skipUnless(TEM_CV2, "opencv-python não instalado")
class DetectarObjetosTestes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_reconhece_formas_basicas(self):
        def desenhar(d):
            d.rectangle((40, 40, 240, 200), fill="black")
            d.ellipse((320, 60, 520, 260), fill="black")
            d.polygon([(300, 440), (420, 300), (540, 440)], fill="black")

        caminho = _imagem(self.base / "formas.png", desenhar, fundo="white")
        resultado = visao.detectar_objetos(str(caminho))
        self.assertTrue(resultado["ok"])
        self.assertEqual(resultado["total"], 3)
        formatos = {o["formato"] for o in resultado["objetos"]}
        self.assertEqual(formatos, {"retângulo", "círculo", "triângulo"})

    def test_imagem_inexistente_devolve_erro_claro(self):
        resultado = visao.detectar_objetos(str(self.base / "nao-existe.png"))
        self.assertFalse(resultado["ok"])
        self.assertIn("não encontrada", resultado["erro"])


class SemOpenCVTestes(unittest.TestCase):
    def test_foto_sem_opencv_explica_o_que_falta(self):
        with patch.object(visao, "_cv2", return_value=None):
            resultado = visao.webcam_foto()
        self.assertFalse(resultado["ok"])
        self.assertIn("opencv-python", resultado["erro"])

    def test_gestos_sem_opencv_nao_quebram(self):
        with patch.object(visao, "_cv2", return_value=None):
            self.assertFalse(visao.detectar_gestos_mao(1)["ok"])
            self.assertFalse(visao.controlar_mouse_com_gesto(1)["ok"])


if __name__ == "__main__":
    unittest.main()
