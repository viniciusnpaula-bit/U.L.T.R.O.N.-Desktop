"""Registro emocional: parser local da marca + prosódia + integração sem IA real."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import registro


class ParserTests(unittest.TestCase):
    def test_reconhece_cada_registro_da_lista(self):
        for nome in registro.REGISTROS:
            with self.subTest(nome=nome):
                achado, texto = registro.extrair(f"[[registro:{nome}]] Tudo certo.")
                self.assertEqual(achado, nome)
                self.assertEqual(texto, "Tudo certo.")

    def test_ausente_cai_em_neutro_sem_mexer_no_texto(self):
        self.assertEqual(registro.extrair("Bom dia, senhor."),
                         ("neutro", "Bom dia, senhor."))
        self.assertEqual(registro.extrair(""), ("neutro", ""))
        self.assertEqual(registro.extrair(None), ("neutro", ""))

    def test_desconhecido_cai_em_neutro_e_remove_a_marca(self):
        self.assertEqual(registro.extrair("[[registro:euforico]] Oi."),
                         ("neutro", "Oi."))

    def test_marca_malformada_cai_em_neutro_e_nao_vaza(self):
        achado, texto = registro.extrair("[[registro:lamento] Lamento, senhor.")
        self.assertEqual(achado, "neutro")
        self.assertEqual(texto, "Lamento, senhor.")

    def test_aceita_espacos_e_maiusculas(self):
        self.assertEqual(registro.extrair("[[ REGISTRO : Alerta ]] Cuidado."),
                         ("alerta", "Cuidado."))


class ProsodiaTests(unittest.TestCase):
    def _json(self, dados):
        arquivo = Path(tempfile.mkdtemp()) / "registros.json"
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
        return arquivo

    def test_neutro_nao_muda_a_voz_configurada(self):
        self.assertEqual(registro.aplicar_voz("neutro", "+0%", "-12Hz"),
                         ("+0%", "-12Hz"))
        self.assertEqual(registro.aplicar_voz("neutro", "+7%", "-4Hz"),
                         ("+7%", "-4Hz"))

    def test_delta_soma_sobre_a_voz_do_painel(self):
        rate, pitch = registro.aplicar_voz("lamento", "+4%", "-12Hz")
        self.assertEqual(rate, "-4%")
        self.assertEqual(pitch, "-20Hz")

    def test_clamp_em_json_absurdo(self):
        arquivo = self._json({
            "lamento": {"rate": 9999, "pitch": -9999},
            "alerta": {"rate": "muito", "pitch": True},
            "comemorando": {"rate": 7.6, "pitch": -7.4},
        })
        with patch.object(registro, "ARQUIVO", arquivo):
            mapa = registro.ajustes()
        for nome, valores in mapa.items():
            with self.subTest(nome=nome):
                self.assertLessEqual(abs(valores["rate"]), registro.LIMITE)
                self.assertLessEqual(abs(valores["pitch"]), registro.LIMITE)
        self.assertEqual(mapa["lamento"], {"rate": 15, "pitch": -15})
        # inválido não contamina: fica o padrão embutido
        self.assertEqual(mapa["alerta"], registro.PADRAO["alerta"])
        self.assertEqual(mapa["comemorando"], {"rate": 8, "pitch": -7})

    def test_json_ausente_usa_padrao_embutido(self):
        with patch.object(registro, "ARQUIVO", Path(tempfile.mkdtemp()) / "sumiu.json"):
            self.assertEqual(registro.ajustes(), registro.PADRAO)

    def test_log_nao_leva_texto_da_conversa(self):
        with patch("seguranca.log") as log:
            registro.registrar("lamento")
        log.info.assert_called_once_with("[registro] lamento")


class IntegracaoCerebroTests(unittest.TestCase):
    def _stream(self, frases, registro_esperado="lamento"):
        import cerebro
        with patch.object(cerebro, "_stream_frases", return_value=iter(frases)), \
                patch.object(cerebro, "_system", lambda: "sys"), \
                patch.object(cerebro, "_provedor_para_stream", lambda: "gemini"), \
                patch.object(cerebro.memoria, "historico", lambda _n: []), \
                patch.object(cerebro.memoria, "salvar_msg"), \
                patch.object(cerebro.seguranca, "parada", SimpleNamespace(clear=lambda: None)), \
                patch.object(cerebro, "_rastrear"), \
                patch.object(registro, "registrar"):
            partes, finalizar = cerebro.processar_stream("oi", None, "teste")
            self.assertEqual(partes.registro, "neutro")
            lidas = list(partes)
            self.assertEqual(partes.registro, registro_esperado)
            completo = finalizar()
        return lidas, completo

    def test_stream_remove_a_marca_da_tela_e_da_fala(self):
        lidas, completo = self._stream(
            ["[[registro:lamento]] Lamento, senhor.", "Vamos vender mais."])
        self.assertEqual(lidas, ["Lamento, senhor.", "Vamos vender mais."])
        self.assertEqual(completo, "Lamento, senhor. Vamos vender mais.")
        for texto in lidas + [completo]:
            self.assertNotIn("[[registro", texto)

    def test_registro_decidido_uma_vez_para_a_resposta(self):
        lidas, _ = self._stream(["[[registro:alerta]] Atenção.",
                                 "[[registro:comemorando]] e isso."],
                                registro_esperado="alerta")
        self.assertEqual(lidas, ["Atenção.", "e isso."])

    def test_marca_ausente_nao_quebra(self):
        lidas, _ = self._stream(["Sem marca."], registro_esperado="neutro")
        self.assertEqual(lidas, ["Sem marca."])

    def test_chamada_de_ferramenta_sem_texto_nao_quebra(self):
        import cerebro
        respostas = [
            SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="call_1", function=SimpleNamespace(name="listar_pasta",
                                                      arguments='{"pasta": "C:/x"}'))]),
            SimpleNamespace(content="[[registro:serio]] Anotado.", tool_calls=[]),
        ]
        with patch.object(cerebro, "_chamar", side_effect=respostas), \
                patch.object(cerebro.ferramentas, "executar", return_value="ok"), \
                patch.object(cerebro, "_rastrear"):
            self.assertEqual(cerebro._loop([], None, "teste"), "Anotado.")

    def test_fala_recebe_texto_limpo_e_o_registro(self):
        import voz
        vistos = []

        async def sintetizar(texto, _arquivo, emocao=registro.NEUTRO):
            vistos.append((texto, emocao))
            Path(_arquivo).write_bytes(b"mp3")

        class Partes(list):
            registro = "lamento"

        partes = Partes(["Lamento, senhor.", "Vamos vender mais."])
        with patch.object(voz, "_sintetizar", sintetizar), \
                patch.object(voz, "_tocar", lambda *_a: None), \
                patch.object(voz, "glob"), \
                patch.object(voz.time, "sleep", lambda *_a: None):
            voz.falar_partes(partes, eco=0)

        self.assertEqual([t for t, _ in vistos], ["Lamento, senhor.", "Vamos vender mais."])
        self.assertTrue(all(e == "lamento" for _, e in vistos))


class RegressaoEstilosTests(unittest.TestCase):
    def test_os_13_estilos_continuam_iguais_com_neutro(self):
        import personalidade
        self.assertEqual(len(personalidade.JEITOS), 13)
        for chave in personalidade.JEITOS:
            with self.subTest(jeito=chave):
                with patch.object(personalidade, "carregar",
                                  lambda chave=chave: {**personalidade._padrao(), "jeito": chave}):
                    frase = personalidade.frase_do_sistema()
                self.assertIn(personalidade.JEITOS[chave]["tom"], frase)

    def test_instrucao_de_registro_entra_no_system_prompt(self):
        import cerebro, personalidade
        with patch.object(personalidade, "carregar", personalidade._padrao):
            frase = cerebro._system()
        self.assertIn("[[registro:NOME]]", frase)
        self.assertIn("Lamento, senhor", frase)


if __name__ == "__main__":
    unittest.main()
