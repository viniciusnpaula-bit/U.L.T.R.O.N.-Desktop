"""Geração de páginas HTML estáticas para a ferramenta `criar_site`."""
from __future__ import annotations

import html as _html
import re
from pathlib import Path

_MODELO_SITE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #07080c; color: #eef1f7;
         font: 16px/1.65 "Segoe UI", system-ui, sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 12vh 24px 16vh; }}
  h1 {{ margin: 0 0 28px; font-size: clamp(34px, 6vw, 58px); line-height: 1.08;
       font-weight: 700; letter-spacing: -.03em; }}
  p {{ margin: 0 0 18px; color: #b9c1cf; max-width: 62ch; }}
  footer {{ margin-top: 64px; padding-top: 18px; border-top: 1px solid #1c2028;
           font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #6d7686; }}
</style>
</head>
<body>
<main>
<h1>{titulo}</h1>
{corpo}
<footer>feito com ULTRON</footer>
</main>
</body>
</html>
"""


def montar_destino_site(base: Path, nome: str) -> Path | None:
    arquivo_nome = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(str(nome or "site")).name).strip(".-")
    if not arquivo_nome:
        arquivo_nome = "site"
    if not arquivo_nome.lower().endswith((".html", ".htm")):
        arquivo_nome += ".html"
    destino = (base / arquivo_nome).resolve()
    if destino.parent != base.resolve():
        return None
    return destino


def gerar_html_site(titulo: str, conteudo: str = "") -> str:
    titulo_limpo = _html.escape(str(titulo or "Sem título").strip() or "Sem título")
    blocos = [b.strip() for b in re.split(r"\n\s*\n", str(conteudo or "")) if b.strip()]
    if blocos:
        corpo = "\n".join("<p>" + _html.escape(b).replace("\n", "<br>") + "</p>" for b in blocos)
    else:
        corpo = "<p>Página criada pelo ULTRON. Edite este arquivo para escrever o conteúdo.</p>"
    return _MODELO_SITE.format(titulo=titulo_limpo, corpo=corpo)
