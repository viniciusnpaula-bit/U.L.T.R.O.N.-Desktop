"""Isola a suíte do banco real.

Sem isto, qualquer teste que chame `memoria` sem patch usa `dados/ultron.db` de
verdade — e a migração cifra o banco do usuário no meio de um `pytest`.
"""
import sqlite3

import pytest

import cofre
import memoria

ESQUEMA = """
CREATE TABLE IF NOT EXISTS mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
"""


def pytest_configure(config):
    memoria._db.close()             # solta o arquivo real antes de qualquer teste


@pytest.fixture(autouse=True)
def banco_isolado(tmp_path, monkeypatch):
    con = sqlite3.connect(str(tmp_path / "teste.db"), check_same_thread=False)
    con.executescript(ESQUEMA)
    monkeypatch.setattr(memoria, "_db", con)
    monkeypatch.setattr(cofre, "ARQUIVO_CHAVE", tmp_path / ".cofre.chave")
    yield
    con.close()
