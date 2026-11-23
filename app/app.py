#!/usr/bin/env python3
"""Kaizen OS — monitor pessoal de hábitos e saúde (só biblioteca padrão do Python 3.9+).

Modelo que evolui sem acumular checklist:
  - `habitos`: cada mini-hábito tem início, status (ativo, consolidado, pausado, arquivado) e fim.
    Limite de hábitos ATIVOS opcional (padrão: sem limite; `config limite 5` para travar em 5).
    Hábitos que viram automáticos se graduam e saem do check-in diário. O histórico fica guardado.
  - `marcas`: uma linha por dia × hábito (sim/não).
  - `checkins`: o resto do dia (sono, tela, energia, ansiedade, nota).
  - `fases`: blocos de tempo (ex.: "Fase 1 · só as âncoras", 14 dias).

Servidor:
  ANCORAS_TOKEN=um-segredo-longo python3 app.py serve [--host 127.0.0.1] [--port 8787]
  Abrir no celular uma vez:  https://SEU-ENDERECO/?k=um-segredo-longo   (vira cookie por 1 ano)

Linha de comando (para você ou para um agente de IA no mesmo servidor):
  app.py set hoje academia=sim nota="Treino leve"   # "hoje", "ontem" ou AAAA-MM-DD
  app.py get hoje | app.py resumo | app.py export registro.csv | app.py import registro.csv
  app.py habitos                                   # lista hábitos e quanto foram cumpridos (21 dias)
  app.py habito novo agua "Beber 2 L de água" "garrafa na mesa" agua 10
  app.py habito graduar celular | pausar ID | reativar ID | arquivar ID
  app.py fase nova "Fase 2 · água" 2026-12-07 2026-12-20
  app.py config nome "Kaizen da Ana" | config limite 5   # 0 = sem limite

Banco: ancoras.db na mesma pasta (ou ANCORAS_DB=/caminho/ancoras.db).
Primeira execução: se existir ANCORAS_SEED (JSON) ou seed.json na pasta, ele define nome, hábitos e fase.
"""
import csv
import hmac
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import saude

PASTA = Path(__file__).resolve().parent
DB = Path(os.environ.get("ANCORAS_DB", PASTA / "ancoras.db"))
TOKEN = os.environ.get("ANCORAS_TOKEN", "")
HOOK_TOKEN = os.environ.get("ANCORAS_HOOK_TOKEN", "")  # só para o webhook do relógio/pulseira (escopo: gravar saúde)
PUBLIC_URL = os.environ.get("ANCORAS_PUBLIC_URL", "").rstrip("/")
TZ = ZoneInfo(os.environ.get("ANCORAS_TZ", "America/Sao_Paulo"))

NUMS = {"sono_h": (0, 14), "tela_h": (0, 24), "energia": (0, 10), "ansiedade": (0, 10)}
CAMPOS_DIA = ["dormiu", "sono_h", "tela_h", "energia", "ansiedade", "nota"]
RESERVADOS = {"data", "atualizado", "fonte", *CAMPOS_DIA}
LEGADO = ["celular", "acordou7", "manha", "academia", "foco"]  # colunas antigas de checkins (migradas para marcas)
STATUS = {"ativo", "consolidado", "pausado", "arquivado"}
SIM, NAO = {"sim", "s", "1", "true", "yes"}, {"nao", "não", "n", "0", "false", "no"}

PADRAO = {
    "nome": "Kaizen OS",
    "limite_ativos": 0,
    "marcos": [],
    "habitos": [
        {"id": "celular", "nome": "Celular fora do quarto", "detalhe": "e fora do banheiro", "icone": "celular", "xp": 15},
        {"id": "acordou7", "nome": "Acordei às 7h", "detalhe": "despertador no pulso", "icone": "acordou7", "xp": 10},
        {"id": "manha", "nome": "Manhã sem celular", "detalhe": "rosto, sol, alongar, café", "icone": "manha", "xp": 10},
        {"id": "academia", "nome": "Academia", "detalhe": "20 minutos já contam", "icone": "academia", "xp": 25},
        {"id": "foco", "nome": "Bloco de foco", "detalhe": "90 min, celular longe", "icone": "foco", "xp": 25},
    ],
    "fase": {"nome": "Fase 1 · só as âncoras", "dias": 14},
}


def hoje():
    """Data local (fuso ANCORAS_TZ), independente do relógio do servidor."""
    return datetime.now(TZ).date()


def agora():
    return datetime.now(TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------- banco
def conectar():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS checkins(
            data TEXT PRIMARY KEY, dormiu TEXT, sono_h REAL, tela_h REAL, energia REAL, ansiedade REAL,
            nota TEXT, atualizado TEXT, fonte TEXT);
        CREATE TABLE IF NOT EXISTS habitos(
            id TEXT PRIMARY KEY, nome TEXT NOT NULL, detalhe TEXT, icone TEXT, xp INTEGER DEFAULT 10,
            inicio TEXT NOT NULL, fim TEXT, status TEXT NOT NULL DEFAULT 'ativo', ordem INTEGER DEFAULT 0,
            criado TEXT);
        CREATE TABLE IF NOT EXISTS marcas(
            data TEXT NOT NULL, habito TEXT NOT NULL, valor INTEGER NOT NULL, atualizado TEXT, fonte TEXT,
            PRIMARY KEY(data, habito));
        CREATE TABLE IF NOT EXISTS fases(
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, inicio TEXT NOT NULL, fim TEXT);
        CREATE TABLE IF NOT EXISTS config(chave TEXT PRIMARY KEY, valor TEXT);
        """
    )
    saude.preparar(con)
    _semear(con)
    return con


def _cfg(con, chave, padrao=None):
    r = con.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    return json.loads(r["valor"]) if r else padrao


def _set_cfg(con, chave, valor):
    con.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (chave, json.dumps(valor, ensure_ascii=False)))


def _semear(con):
    """Primeira execução: cria hábitos/fase a partir do seed e migra colunas antigas de checkins."""
    if con.execute("SELECT COUNT(*) FROM habitos").fetchone()[0]:
        return
    seed = PADRAO
    arq = os.environ.get("ANCORAS_SEED") or (PASTA / "seed.json")
    if Path(arq).exists():
        seed = {**PADRAO, **json.loads(Path(arq).read_text(encoding="utf-8"))}
    colunas = {r[1] for r in con.execute("PRAGMA table_info(checkins)")}
    legado = [c for c in LEGADO if c in colunas]
    primeiro = None
    if legado:
        cond = " OR ".join(f"{c} IS NOT NULL" for c in legado)
        r = con.execute(f"SELECT MIN(data) FROM checkins WHERE {cond}").fetchone()
        primeiro = r[0]
    inicio_fase = seed.get("fase", {}).get("inicio") or primeiro or hoje().isoformat()
    inicio_hab = min(filter(None, [primeiro, inicio_fase]))
    for i, h in enumerate(seed["habitos"]):
        con.execute(
            "INSERT INTO habitos(id,nome,detalhe,icone,xp,inicio,status,ordem,criado) VALUES (?,?,?,?,?,?,?,?,?)",
            (h["id"], h["nome"], h.get("detalhe", ""), h.get("icone", "check"), int(h.get("xp", 10)),
             h.get("inicio", inicio_hab), "ativo", i, agora()),
        )
    f = seed.get("fase") or {}
    if f:
        fim = f.get("fim") or (datetime.fromisoformat(inicio_fase) + timedelta(days=int(f.get("dias", 14)) - 1)).date().isoformat()
        con.execute("INSERT INTO fases(nome,inicio,fim) VALUES (?,?,?)", (f.get("nome", "Fase 1"), inicio_fase, fim))
    _set_cfg(con, "nome", seed.get("nome", "Âncoras"))
    _set_cfg(con, "limite_ativos", int(seed.get("limite_ativos", 0)))
    _set_cfg(con, "marcos", seed.get("marcos", []))
    _set_cfg(con, "relogio", seed.get("relogio", "Relógio"))
    _set_cfg(con, "combinados", seed.get("combinados", []))
    for c in legado:  # migração: colunas booleanas antigas -> marcas
        for r in con.execute(f"SELECT data, {c}, atualizado, fonte FROM checkins WHERE {c} IS NOT NULL").fetchall():
            con.execute("INSERT OR REPLACE INTO marcas VALUES (?,?,?,?,?)", (r["data"], c, int(r[c]), r["atualizado"], r["fonte"]))
    con.commit()


def habitos(con, incluir_arquivados=False):
    sql = "SELECT * FROM habitos" + ("" if incluir_arquivados else " WHERE status!='arquivado'") + " ORDER BY ordem, inicio"
    return [dict(r) for r in con.execute(sql)]


def ids_habitos(con):
    return [r["id"] for r in con.execute("SELECT id FROM habitos ORDER BY ordem, inicio")]


def ativo_em(h, dia):
    return h["inicio"] <= dia and (h["fim"] is None or dia <= h["fim"]) and h["status"] != "arquivado"


# ---------------------------------------------------------------- dia
def validar_data(s):
    s = (s or "").strip().lower()
    if s == "hoje":
        return hoje().isoformat()
    if s == "ontem":
        return (hoje() - timedelta(days=1)).isoformat()
    datetime.strptime(s, "%Y-%m-%d")
    return s


def _bool(k, v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return int(v)
    t = str(v).strip().lower()
    if t in SIM:
        return 1
    if t in NAO:
        return 0
    raise ValueError(f"{k}: use sim, nao ou vazio")


def normalizar(con, campos):
    """Separa e valida: hábitos -> marcas; o resto -> checkins. None ou "" apagam o campo."""
    ids = set(ids_habitos(con))
    m, c = {}, {}
    for k, v in campos.items():
        if k in ids:
            m[k] = _bool(k, v)
        elif k in NUMS:
            if v is None or v == "":
                c[k] = None
                continue
            try:
                x = float(str(v).replace(",", "."))
            except ValueError:
                raise ValueError(f"{k}: precisa ser número")
            lo, hi = NUMS[k]
            if not lo <= x <= hi:
                raise ValueError(f"{k}: entre {lo} e {hi}")
            c[k] = x
        elif k == "dormiu":
            v = (v or "").strip()
            if v and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                raise ValueError("dormiu: use HH:MM")
            c[k] = v or None
        elif k == "nota":
            c[k] = (str(v or "").strip()[:500]) or None
        else:
            raise ValueError(f"campo desconhecido: {k} (hábitos: {', '.join(sorted(ids))})")
    return m, c


def dia_dict(con, dia):
    r = con.execute("SELECT * FROM checkins WHERE data=?", (dia,)).fetchone()
    d = {"data": dia}
    if r:
        for k in CAMPOS_DIA + ["atualizado", "fonte"]:
            if r[k] not in (None, ""):
                d[k] = r[k]
    for mk in con.execute("SELECT habito, valor FROM marcas WHERE data=?", (dia,)):
        d[mk["habito"]] = bool(mk["valor"])
    return d


def gravar(con, dia, campos, fonte):
    dia = validar_data(dia)
    m, c = normalizar(con, campos)
    ts = agora()
    con.execute("INSERT OR IGNORE INTO checkins(data) VALUES (?)", (dia,))
    if c:
        sets = ", ".join(f"{k}=?" for k in c)
        con.execute(f"UPDATE checkins SET {sets}, atualizado=?, fonte=? WHERE data=?", [*c.values(), ts, fonte, dia])
    for h, v in m.items():
        if v is None:
            con.execute("DELETE FROM marcas WHERE data=? AND habito=?", (dia, h))
        else:
            con.execute("INSERT OR REPLACE INTO marcas VALUES (?,?,?,?,?)", (dia, h, v, ts, fonte))
    if m and not c:
        con.execute("UPDATE checkins SET atualizado=?, fonte=? WHERE data=?", (ts, fonte, dia))
    con.commit()
    return dia_dict(con, dia)


def listar(con, dias=120):
    inicio = (hoje() - timedelta(days=dias)).isoformat()
    datas = {r[0] for r in con.execute("SELECT data FROM checkins WHERE data>=?", (inicio,))}
    datas |= {r[0] for r in con.execute("SELECT DISTINCT data FROM marcas WHERE data>=?", (inicio,))}
    return [dia_dict(con, d) for d in sorted(datas)]


def exportar_csv(con):
    ids = ids_habitos(con)
    cols = ["data", *ids, *CAMPOS_DIA]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for d in listar(con, 36500):
        linha = []
        for k in cols:
            v = d.get(k)
            if k in ids:
                v = "" if v is None else ("sim" if v else "nao")
            elif v is None:
                v = ""
            elif isinstance(v, float) and v.is_integer():
                v = int(v)
            linha.append(v)
        w.writerow(linha)
    return buf.getvalue()


def taxa(con, hid, dias=21):
    """% cumprido nos últimos N dias em que o hábito estava ativo (e quantos dias foram marcados)."""
    ini = (hoje() - timedelta(days=dias - 1)).isoformat()
    r = con.execute("SELECT SUM(valor) s, COUNT(*) n FROM marcas WHERE habito=? AND data>=?", (hid, ini)).fetchone()
    return (r["s"] or 0), (r["n"] or 0)


def resumo(con):
    dia_atual = hoje()
    hs = habitos(con)
    linhas = []
    for i in range(6, -1, -1):
        d = (dia_atual - timedelta(days=i)).isoformat()
        x = dia_dict(con, d)
        ativos = [h for h in hs if ativo_em(h, d)]
        marcas = " ".join(f"{h['id']}:{'✓' if x.get(h['id']) is True else '✗' if x.get(h['id']) is False else '–'}" for h in ativos)
        extra = f" sono:{x['sono_h']}h" if x.get("sono_h") is not None else ""
        linhas.append(f"{d}: {marcas}{extra}")
    return "\n".join(linhas)


# ---------------------------------------------------------------- hábitos e fases
ID_RE = re.compile(r"[a-z][a-z0-9_]{1,23}")


def habito_novo(con, hid, nome, detalhe="", icone="check", xp=10, inicio=None):
    hid = hid.strip().lower()
    if not ID_RE.fullmatch(hid) or hid in RESERVADOS:
        raise ValueError("id: minúsculas, números e _, 2 a 24 caracteres, sem nomes reservados")
    if con.execute("SELECT 1 FROM habitos WHERE id=?", (hid,)).fetchone():
        raise ValueError(f"já existe um hábito '{hid}' (use reativar)")
    limite = _cfg(con, "limite_ativos", 0)
    ativos = con.execute("SELECT COUNT(*) FROM habitos WHERE status='ativo'").fetchone()[0]
    if limite and ativos >= limite:
        raise ValueError(f"limite de {limite} hábitos ativos. Gradue (consolidado) ou pause um antes de começar outro.")
    if not str(nome).strip():
        raise ValueError("nome obrigatório")
    xp = int(xp)
    if not 1 <= xp <= 50:
        raise ValueError("xp entre 1 e 50")
    ordem = (con.execute("SELECT MAX(ordem) FROM habitos").fetchone()[0] or 0) + 1
    con.execute(
        "INSERT INTO habitos(id,nome,detalhe,icone,xp,inicio,status,ordem,criado) VALUES (?,?,?,?,?,?,?,?,?)",
        (hid, str(nome).strip()[:60], str(detalhe or "").strip()[:80], str(icone or "check")[:16], xp,
         validar_data(inicio or "hoje"), "ativo", ordem, agora()),
    )
    con.commit()
    return dict(con.execute("SELECT * FROM habitos WHERE id=?", (hid,)).fetchone())


def habito_status(con, hid, acao, quando=None):
    h = con.execute("SELECT * FROM habitos WHERE id=?", (hid,)).fetchone()
    if not h:
        raise ValueError(f"hábito '{hid}' não existe")
    dia = validar_data(quando or "hoje")
    if acao in ("graduar", "consolidar"):
        con.execute("UPDATE habitos SET status='consolidado', fim=? WHERE id=?", (dia, hid))
    elif acao == "pausar":
        con.execute("UPDATE habitos SET status='pausado', fim=? WHERE id=?", (dia, hid))
    elif acao == "arquivar":
        con.execute("UPDATE habitos SET status='arquivado', fim=COALESCE(fim, ?) WHERE id=?", (dia, hid))
    elif acao == "reativar":
        limite = _cfg(con, "limite_ativos", 0)
        ativos = con.execute("SELECT COUNT(*) FROM habitos WHERE status='ativo'").fetchone()[0]
        if limite and h["status"] != "ativo" and ativos >= limite:
            raise ValueError(f"limite de {limite} hábitos ativos")
        con.execute("UPDATE habitos SET status='ativo', fim=NULL WHERE id=?", (hid,))
    else:
        raise ValueError("ação: graduar, pausar, arquivar ou reativar")
    con.commit()
    return dict(con.execute("SELECT * FROM habitos WHERE id=?", (hid,)).fetchone())


def habito_editar(con, hid, campos):
    permitidos = {"nome": 60, "detalhe": 80, "icone": 16}
    sets = {k: str(v).strip()[:permitidos[k]] for k, v in campos.items() if k in permitidos and v is not None}
    if "xp" in campos:
        sets["xp"] = max(1, min(50, int(campos["xp"])))
    if not sets:
        raise ValueError("nada para alterar")
    con.execute(f"UPDATE habitos SET {', '.join(k + '=?' for k in sets)} WHERE id=?", [*sets.values(), hid])
    con.commit()
    return dict(con.execute("SELECT * FROM habitos WHERE id=?", (hid,)).fetchone())


def fase_nova(con, nome, inicio, fim=None):
    ini = validar_data(inicio)
    f = validar_data(fim) if fim else None
    con.execute("UPDATE fases SET fim=? WHERE fim IS NULL OR fim>=?", ((datetime.fromisoformat(ini) - timedelta(days=1)).date().isoformat(), ini))
    con.execute("INSERT INTO fases(nome,inicio,fim) VALUES (?,?,?)", (nome, ini, f))
    con.commit()


def estrutura(con):
    hs = habitos(con)
    for h in hs:
        s, n = taxa(con, h["id"])
        h["cumpridos21"], h["marcados21"] = s, n
    return {
        "nome": _cfg(con, "nome", "Kaizen OS"),
        "limite_ativos": _cfg(con, "limite_ativos", 0),
        "marcos": _cfg(con, "marcos", []),
        "relogio": _cfg(con, "relogio", "Relógio"),
        "combinados": _cfg(con, "combinados", []),
        "habitos": hs,
        "fases": [dict(r) for r in con.execute("SELECT * FROM fases ORDER BY inicio")],
    }


# ---------------------------------------------------------------- web
ESTATICOS = {
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),
    "/jogo.js": ("jogo.js", "text/javascript; charset=utf-8"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
    "/icon-maskable-512.png": ("icon-maskable-512.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/favicon.ico": ("icon-192.png", "image/png"),
}


class App(BaseHTTPRequestHandler):
    server_version = "KaizenOS/2.0"

    def log_message(self, fmt, *args):  # log curto, sem querystring (o token não vai pro log)
        sys.stderr.write("%s %s\n" % (self.command, urlparse(self.path).path))

    def _autorizado(self):
        if not TOKEN:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], TOKEN):
            return True
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "ancoras" in c and hmac.compare_digest(c["ancoras"].value, TOKEN)

    def _enviar(self, status, corpo, tipo="application/json; charset=utf-8", extra=None):
        dados = corpo if isinstance(corpo, bytes) else corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, status, obj):
        self._enviar(status, json.dumps(obj, ensure_ascii=False))

    def _corpo(self, limite=20000):
        n = int(self.headers.get("Content-Length", "0"))
        if n > limite:
            raise ValueError("corpo grande demais")
        obj = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(obj, dict):
            raise ValueError("envie um objeto JSON")
        return obj

    def do_GET(self):
        u = urlparse(self.path)
        k = parse_qs(u.query).get("k", [""])[0]
        if u.path == "/" and k and TOKEN and hmac.compare_digest(k, TOKEN):
            https = self.headers.get("X-Forwarded-Proto") == "https" or bool(PUBLIC_URL.startswith("https"))
            ck = f"ancoras={TOKEN}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if https else "")
            return self._enviar(303, "", extra={"Location": "/", "Set-Cookie": ck})
        if u.path == "/saude":
            return self._json(200, {"ok": True})
        if u.path in ESTATICOS:  # PWA: manifest, service worker e ícones (sem dados pessoais)
            nome, tipo = ESTATICOS[u.path]
            extra = {"Service-Worker-Allowed": "/"} if nome == "sw.js" else None
            return self._enviar(200, (PASTA / "static" / nome).read_bytes(), tipo, extra)
        if not self._autorizado():
            return self._enviar(401, "<h1>401</h1><p>Abra o link com ?k=SEU_TOKEN uma vez.</p>", "text/html; charset=utf-8")
        if u.path == "/":
            return self._enviar(200, (PASTA / "index.html").read_bytes(), "text/html; charset=utf-8")
        with conectar() as con:
            q = parse_qs(u.query)
            if u.path == "/api/checkins":
                try:
                    dias = int(q.get("dias", ["120"])[0])
                except ValueError:
                    return self._json(400, {"erro": "dias precisa ser inteiro"})
                return self._json(200, listar(con, min(max(dias, 1), 3650)))
            if u.path == "/api/habitos":
                return self._json(200, estrutura(con))
            if u.path == "/api/webhook":
                if not HOOK_TOKEN:
                    return self._json(200, {"ativo": False})
                base = PUBLIC_URL or f"https://{self.headers.get('Host', '')}"
                return self._json(200, {"ativo": True, "url": f"{base}/api/health?t={HOOK_TOKEN}"})
            if u.path == "/api/saude":
                try:
                    dias = min(max(int(q.get("dias", ["30"])[0]), 1), 400)
                except ValueError:
                    return self._json(400, {"erro": "dias precisa ser inteiro"})
                fim = hoje()
                ini = fim - timedelta(days=dias - 1)
                est = q.get("estagios", [fim.isoformat()])[0]
                return self._json(200, saude.resumo_dias(con, ini.isoformat(), fim.isoformat(), est))
            if u.path == "/api/inventario":
                return self._json(200, saude.inventario(con))
            if u.path == "/api/export.csv":
                return self._enviar(200, exportar_csv(con), "text/csv; charset=utf-8")
        self._json(404, {"erro": "não encontrado"})

    def _hook_autorizado(self):
        if not HOOK_TOKEN:
            return False
        cand = [parse_qs(urlparse(self.path).query).get("t", [""])[0], self.headers.get("X-Api-Key", "")]
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            cand.append(auth[7:])
        return any(c and hmac.compare_digest(c, HOOK_TOKEN) for c in cand)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            if not self._hook_autorizado():
                return self._json(401, {"erro": "não autorizado"})
            try:
                payload = self._corpo(50_000_000)
                with conectar() as con:
                    self._json(200, saude.ingerir(con, payload, gravar))
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                self._json(400, {"erro": f"payload inválido: {e}"})
            return
        if not self._autorizado():
            return self._json(401, {"erro": "não autorizado"})
        try:
            if path == "/api/habitos":
                b = self._corpo()
                with conectar() as con:
                    return self._json(200, habito_novo(con, b.get("id", ""), b.get("nome", ""), b.get("detalhe", ""),
                                                       b.get("icone", "check"), b.get("xp", 10)))
            m = re.fullmatch(r"/api/habitos/([a-z0-9_]+)/(graduar|pausar|arquivar|reativar)", path)
            if m:
                with conectar() as con:
                    return self._json(200, habito_status(con, m.group(1), m.group(2)))
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"erro": str(e)})
        self._json(404, {"erro": "não encontrado"})

    def do_PATCH(self):
        if not self._autorizado():
            return self._json(401, {"erro": "não autorizado"})
        path = urlparse(self.path).path
        try:
            m = re.fullmatch(r"/api/checkins/(\d{4}-\d{2}-\d{2}|hoje|ontem)", path)
            if m:
                campos = self._corpo()
                fonte = str(self.headers.get("X-Fonte", "app"))[:20]
                with conectar() as con:
                    return self._json(200, gravar(con, m.group(1), campos, fonte))
            m = re.fullmatch(r"/api/habitos/([a-z0-9_]+)", path)
            if m:
                with conectar() as con:
                    return self._json(200, habito_editar(con, m.group(1), self._corpo()))
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"erro": str(e)})
        self._json(404, {"erro": "não encontrado"})


# ---------------------------------------------------------------- cli
def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "serve":
        if not TOKEN or len(TOKEN) < 16:
            print("Defina ANCORAS_TOKEN com pelo menos 16 caracteres.", file=sys.stderr)
            return 2
        host = args[args.index("--host") + 1] if "--host" in args else "127.0.0.1"
        port = int(args[args.index("--port") + 1]) if "--port" in args else 8787
        conectar().close()
        print(f"Kaizen OS em http://{host}:{port}")
        ThreadingHTTPServer((host, port), App).serve_forever()
        return 0
    con = conectar()
    try:
        if cmd == "set":
            dia, pares = args[0], args[1:]
            campos = {}
            for p in pares:
                k, _, v = p.partition("=")
                campos[k.strip()] = v
            print(json.dumps(gravar(con, dia, campos, "hermes"), ensure_ascii=False))
        elif cmd == "get":
            print(json.dumps(dia_dict(con, validar_data(args[0])), ensure_ascii=False))
        elif cmd == "resumo":
            print(resumo(con))
        elif cmd == "export":
            Path(args[0]).write_text(exportar_csv(con), encoding="utf-8")
            print(f"exportado para {args[0]}")
        elif cmd == "import":
            n = 0
            with open(args[0], encoding="utf-8", newline="") as f:
                for linha in csv.DictReader(f):
                    dia = linha.pop("data")
                    gravar(con, dia, {k: v for k, v in linha.items() if v != "" or k in CAMPOS_DIA}, "import")
                    n += 1
            print(f"{n} dia(s) importados")
        elif cmd == "habitos":
            e = estrutura(con)
            print(f"{e['nome']} · " + (f"limite de {e['limite_ativos']} ativos" if e["limite_ativos"] else "sem limite de ativos"))
            for h in e["habitos"]:
                pct = f"{round(h['cumpridos21'] / h['marcados21'] * 100)}%" if h["marcados21"] else "–"
                fim = f" até {h['fim']}" if h["fim"] else ""
                print(f"  [{h['status']}] {h['id']}: {h['nome']} · desde {h['inicio']}{fim} · 21d: {pct} ({h['cumpridos21']}/{h['marcados21']})")
        elif cmd == "habito":
            acao = args[0]
            if acao == "novo":
                hid, nome = args[1], args[2]
                detalhe = args[3] if len(args) > 3 else ""
                icone = args[4] if len(args) > 4 else "check"
                xp = args[5] if len(args) > 5 else 10
                print(json.dumps(habito_novo(con, hid, nome, detalhe, icone, xp), ensure_ascii=False))
            elif acao == "editar":
                campos = dict(p.partition("=")[::2] for p in args[2:])
                print(json.dumps(habito_editar(con, args[1], campos), ensure_ascii=False))
            else:
                print(json.dumps(habito_status(con, args[1], acao, args[2] if len(args) > 2 else None), ensure_ascii=False))
        elif cmd == "fase":
            if args[0] != "nova":
                raise ValueError("use: fase nova NOME INICIO [FIM]")
            fase_nova(con, args[1], args[2], args[3] if len(args) > 3 else None)
            print("ok")
        elif cmd == "config":
            chave, valor = args[0], args[1]
            if chave == "limite":
                _set_cfg(con, "limite_ativos", int(valor))
            elif chave == "nome":
                _set_cfg(con, "nome", valor)
            elif chave == "relogio":
                _set_cfg(con, "relogio", valor)
            elif chave in ("marcos", "combinados"):
                _set_cfg(con, chave, json.loads(valor))
            else:
                raise ValueError("config: nome, limite, relogio, marcos ou combinados")
            con.commit()
            print("ok")
        else:
            print(f"comando desconhecido: {cmd}", file=sys.stderr)
            return 2
    except (ValueError, IndexError, json.JSONDecodeError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
