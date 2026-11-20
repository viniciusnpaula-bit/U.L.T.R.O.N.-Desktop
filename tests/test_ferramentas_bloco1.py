import pytest
import ferramentas
import autoconhecimento


def test_todas_ferramentas_bloco1_registradas_no_catalogo():
    novas = [
        "organizar_pdf_downloads",
        "extrair_e_limpar_instalador",
        "limpar_duplicados",
        "limpar_disco",
        "converter_imagens",
        "arquivar_projetos_antigos",
        "executar_backup_incremental",
        "arquivar_capturas_desktop",
        "corrigir_permissoes_pasta",
        "ejetar_usb_ocioso",
        "configurar_bloco1",
    ]
    for nome in novas:
        assert nome in ferramentas.FERRAMENTAS, f"Ferramenta {nome} não registrada em ferramentas.FERRAMENTAS"


def test_autoconhecimento_contem_ferramentas_bloco1():
    grupo_arquivos = autoconhecimento.GRUPOS_FERRAMENTAS.get("arquivos e pastas", [])
    assert "organizar_pdf_downloads" in grupo_arquivos
    assert "limpar_duplicados" in grupo_arquivos
    assert "converter_imagens" in grupo_arquivos
    assert "configurar_bloco1" in grupo_arquivos


def test_autoconhecimento_limites_atualizado():
    limites_str = " ".join(autoconhecimento.LIMITES)
    assert "apenas conversão de formato" in limites_str
