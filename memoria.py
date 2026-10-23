"""Memória do Ultron em SQLite: conversas, fatos sobre o usuário e lembretes."""
import sqlite3
import threading
import time

from config import BASE

_lock = threading.Lock()
_db = sqlite3.connect(str(BASE / "dados" / "ultron.db"), check_same_thread=False)
_db.executescript("""
CREATE TABLE IF NOT EXISTS mensagens(id INTEGER PRIMARY KEY, ts REAL, papel TEXT, texto TEXT);
CREATE TABLE IF NOT EXISTS fatos(id INTEGER PRIMARY KEY, texto TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS lembretes(id INTEGER PRIMARY KEY, due REAL, texto TEXT, feito INTEGER DEFAULT 0);
""")


def _x(sql, args=(), buscar=False):
    with _lock:
        cur = _db.execute(sql, args)
        _db.commit()
        return cur.fetchall() if buscar else cur.lastrowid


def salvar_msg(papel, texto):
    _x("INSERT INTO mensagens(ts, papel, texto) VALUES(?,?,?)", (time.time(), papel, texto))


def historico(n=16):
    linhas = _x("SELECT papel, texto FROM mensagens ORDER BY id DESC LIMIT ?", (n,), True)
    msgs = [{"role": p, "content": t} for p, t in reversed(linhas)]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


class MemoriaLimite(ValueError):
    """Fato recusado por tamanho, quantidade ou busca insegura."""


def _limites():
    """Lê os limites de config sem quebrar se o módulo mudou."""
    try:
        import config
        return (int(getattr(config, "FATO_MAX_CARACTERES", 300)),
                int(getattr(config, "FATO_MAX_TOTAL", 50)),
                int(getattr(config, "FATO_MIN_BUSCA", 3)))
    except Exception:
        return 300, 50, 3


def escapar_like(trecho: str) -> str:
    """Neutraliza % e _ para que a busca seja literal (ESCAPE '\\')."""
    return (str(trecho).replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


def salvar_fato(texto):
    maximo, total_max, _ = _limites()
    limpo = " ".join(str(texto or "").split())
    if not limpo:
        raise MemoriaLimite("Não guardei nada: o fato estava vazio.")
    if len(limpo) > maximo:
        raise MemoriaLimite(f"O fato tem {len(limpo)} caracteres; o limite é {maximo}.")
    if len(listar_fatos()) >= total_max and limpo not in listar_fatos():
        raise MemoriaLimite(f"A memória já tem {total_max} fatos. Apague algum antes de guardar outro.")
    _x("INSERT OR IGNORE INTO fatos(texto) VALUES(?)", (limpo,))


def listar_fatos():
    return [r[0] for r in _x("SELECT texto FROM fatos ORDER BY id", (), True)]


def buscar_fatos(termo, limite=10):
    """Busca literal (sem curinga) entre os fatos guardados."""
    limpo = str(termo or "").strip()
    if not limpo:
        return listar_fatos()[:limite]
    padrao = f"%{escapar_like(limpo)}%"
    linhas = _x("SELECT id, texto FROM fatos WHERE texto LIKE ? ESCAPE '\\' ORDER BY id LIMIT ?",
                (padrao, int(limite)), True)
    return [{"id": linhas_id, "texto": texto} for linhas_id, texto in linhas]


def fatos_centrais(limite=8):
    """Poucos fatos para o contexto curto: os mais recentes e os mais curtos
    (fatos curtos costumam ser os essenciais: nome, cidade, preferências)."""
    linhas = _x("SELECT id, texto FROM fatos ORDER BY id DESC LIMIT ?", (int(limite) * 2,), True)
    escolhidos = sorted(linhas, key=lambda par: (len(par[1]), -par[0]))[:limite]
    return [texto for _, texto in sorted(escolhidos, key=lambda par: par[0])]


def corrigir_fato(id_, texto):
    maximo, _, _ = _limites()
    limpo = " ".join(str(texto or "").split())
    if not limpo:
        raise MemoriaLimite("O fato não pode ficar vazio.")
    if len(limpo) > maximo:
        raise MemoriaLimite(f"O fato tem {len(limpo)} caracteres; o limite é {maximo}.")
    _x("UPDATE fatos SET texto = ? WHERE id = ?", (limpo, int(id_)))
    return True


def apagar_fato_por_id(id_):
    antes = _x("SELECT COUNT(*) FROM fatos WHERE id = ?", (int(id_),), True)[0][0]
    _x("DELETE FROM fatos WHERE id = ?", (int(id_),))
    return antes > 0


def apagar_fato(trecho):
    """Apaga fatos que contenham o trecho. Exige 3 caracteres úteis e trata % e _
    como texto comum (antes, "%%%" apagava todos os fatos)."""
    _, _, minimo = _limites()
    bruto = str(trecho or "")
    uteis = [c for c in bruto if c.isalnum()]
    if len(uteis) < minimo:
        raise MemoriaLimite(
            f"Preciso de pelo menos {minimo} caracteres de verdade para apagar (ex.: \"senha do wifi\").")
    padrao = f"%{escapar_like(bruto.strip())}%"
    antes = _x("SELECT COUNT(*) FROM fatos", (), True)[0][0]
    _x("DELETE FROM fatos WHERE texto LIKE ? ESCAPE '\\'", (padrao,))
    depois = _x("SELECT COUNT(*) FROM fatos", (), True)[0][0]
    return antes - depois


def add_lembrete(due, texto):
    return _x("INSERT INTO lembretes(due, texto) VALUES(?,?)", (due, texto))


def lembretes_vencidos():
    return _x("SELECT id, texto FROM lembretes WHERE feito=0 AND due<=?", (time.time(),), True)


def lembretes_pendentes():
    return _x("SELECT due, texto FROM lembretes WHERE feito=0 ORDER BY due", (), True)


def cancelar_lembrete(numero=None, trecho=""):
    """Cancela um lembrete pendente. Sem alvo claro, recusa (nunca apaga todos)."""
    pendentes = _x("SELECT id, texto FROM lembretes WHERE feito=0 ORDER BY due", (), True)
    if not pendentes:
        return "Não há lembretes pendentes."
    if numero is not None:
        try:
            indice = int(numero)
        except (TypeError, ValueError):
            raise MemoriaLimite("O número do lembrete precisa ser inteiro.") from None
        if not 1 <= indice <= len(pendentes):
            raise MemoriaLimite(f"Só existem {len(pendentes)} lembrete(s) pendentes.")
        alvo_id, texto = pendentes[indice - 1]
        _x("DELETE FROM lembretes WHERE id = ?", (alvo_id,))
        return f"Lembrete cancelado: {texto}"
    limpo = " ".join(str(trecho or "").split())
    if len([c for c in limpo if c.isalnum()]) < 3:
        raise MemoriaLimite("Diga o número do lembrete ou um trecho com pelo menos 3 letras.")
    padrao = f"%{escapar_like(limpo)}%"
    alvos = _x("SELECT id, texto FROM lembretes WHERE feito=0 AND texto LIKE ? ESCAPE '\\'",
               (padrao,), True)
    if not alvos:
        return "Não achei lembrete com esse trecho."
    if len(alvos) > 1:
        lista = "; ".join(f"{i + 1}) {texto}" for i, (_id, texto) in enumerate(pendentes))
        raise MemoriaLimite(f"Mais de um lembrete combina. Diga o número: {lista}")
    _x("DELETE FROM lembretes WHERE id = ?", (alvos[0][0],))
    return f"Lembrete cancelado: {alvos[0][1]}"


def lembretes_numerados():
    """Lista com número, hora local e texto — a base para cancelar por número."""
    import datetime as _dt
    itens = []
    for indice, (due, texto) in enumerate(_x(
            "SELECT due, texto FROM lembretes WHERE feito=0 ORDER BY due", (), True), start=1):
        quando = _dt.datetime.fromtimestamp(due).strftime("%d/%m %H:%M")
        itens.append({"numero": indice, "quando": due, "hora_local": quando, "texto": texto})
    return itens


def marcar_feito(id_):
    _x("UPDATE lembretes SET feito=1 WHERE id=?", (id_,))
