"""Dados de saúde vindos do relógio/pulseira (app do fabricante → Health Connect → HC Webhook → POST /api/health).

Guarda todo registro em `hc_registros` (upsert por id do Health Connect), mantém os payloads brutos
compactados em disco (sem truncar) e calcula o resumo diário usado pelo monitor.
"""
import gzip
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("ANCORAS_TZ", "America/Sao_Paulo"))
PASTA_BRUTO = Path(os.environ.get("ANCORAS_PAYLOADS", Path.home() / ".local/share/ancoras/payloads"))
MANTER_BRUTOS = 200
# Calorias totais vêm do app Fitbit/Google Health (gasto basal minuto a minuto): só ruído aqui.
IGNORAR = {"total_calories"}

# Estágios do Health Connect (SleepSessionRecord.STAGE_TYPE_*)
FASES = {"0": "desconhecido", "1": "acordado", "2": "dormindo", "3": "fora_da_cama",
         "4": "leve", "5": "profundo", "6": "rem", "7": "acordado"}
ACORDADO = {"acordado", "fora_da_cama"}

# Campo numérico principal de cada tipo
VALOR = {
    "steps": "count", "distance": "meters", "active_calories": "calories", "total_calories": "calories",
    "heart_rate": "bpm", "resting_heart_rate": "bpm", "heart_rate_variability": "rmssd_millis",
    "oxygen_saturation": "percentage", "respiratory_rate": "rate", "weight": "kilograms",
    "body_fat": "percentage", "exercise": "duration_seconds", "sleep": "duration_seconds",
    "hydration": "liters", "vo2_max": "vo2_ml_per_min_kg", "skin_temperature": "delta_celsius",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hc_registros(
    chave TEXT PRIMARY KEY, tipo TEXT NOT NULL, dia TEXT NOT NULL, inicio TEXT, fim TEXT,
    valor REAL, dados TEXT, origem TEXT, recebido TEXT);
CREATE INDEX IF NOT EXISTS hc_tipo_dia ON hc_registros(tipo, dia);
"""


def preparar(con):
    con.executescript(SCHEMA)


def instante(s):
    """ISO-8601 (Z ou offset) -> datetime em Brasília."""
    dt = datetime.fromisoformat(str(s).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)


def _guardar_bruto(payload):
    PASTA_BRUTO.mkdir(parents=True, exist_ok=True)
    nome = datetime.now(TZ).strftime("%Y%m%d-%H%M%S-%f") + ".json.gz"
    with gzip.open(PASTA_BRUTO / nome, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    for velho in sorted(PASTA_BRUTO.glob("*.json.gz"))[:-MANTER_BRUTOS]:
        velho.unlink(missing_ok=True)


def _sono(rec):
    fim = instante(rec["session_end_time"])
    dur = int(rec.get("duration_seconds") or 0)
    fases, inicio = {}, None
    for st in rec.get("stages") or []:
        nome = FASES.get(str(st.get("stage")), "desconhecido")
        fases[nome] = fases.get(nome, 0) + int(st.get("duration_seconds") or 0)
        i = instante(st["start_time"])
        inicio = i if inicio is None or i < inicio else inicio
    inicio = inicio or fim - timedelta(seconds=dur)
    dormindo = sum(v for k, v in fases.items() if k not in ACORDADO) or dur
    return inicio, fim, dormindo, fases


def ingerir(con, payload, gravar_checkin):
    """Upsert de todos os registros; recalcula sono do check-in nos dias afetados.
    `gravar_checkin(con, dia, campos, fonte)` vem do app (evita import circular)."""
    preparar(con)
    _guardar_bruto(payload)
    agora = datetime.now(TZ).isoformat(timespec="seconds")
    contagem, dias_sono = {}, set()
    for tipo, lista in payload.items():
        if tipo == "deleted" or tipo in IGNORAR or not isinstance(lista, list):
            continue
        for rec in lista:
            if not isinstance(rec, dict):
                continue
            meta = rec.get("metadata") or {}
            dados = {k: v for k, v in rec.items() if k != "metadata"}
            if tipo == "sleep":
                inicio, fim, dormindo, fases = _sono(rec)
                dia = fim.date().isoformat()
                valor = dormindo
                dados = {"dormindo_s": dormindo, "duracao_s": int(rec.get("duration_seconds") or 0),
                         "fases": fases, "estagios": rec.get("stages") or []}
                dias_sono.add(dia)
            else:
                t0 = rec.get("start_time") or rec.get("time")
                t1 = rec.get("end_time") or t0
                if not t0:
                    continue
                inicio, fim = instante(t0), instante(t1)
                dia = inicio.date().isoformat()
                v = rec.get(VALOR.get(tipo, ""), rec.get("avg"))
                valor = float(v) if isinstance(v, (int, float)) else None
            if meta.get("id"):
                # agregados por minuto herdam o id da 1ª amostra, então o início entra na chave
                chave = f"{tipo}|{meta['id']}|{inicio.isoformat()}"
            elif (fim - inicio) >= timedelta(hours=2):  # agregado diário: 1 linha por dia
                chave = f"{tipo}|dia|{dia}"
            else:
                chave = f"{tipo}|{inicio.isoformat()}"
            con.execute(
                "INSERT OR REPLACE INTO hc_registros VALUES (?,?,?,?,?,?,?,?,?)",
                (chave, tipo, dia, inicio.isoformat(), fim.isoformat(), valor,
                 json.dumps(dados, ensure_ascii=False), meta.get("data_origin"), agora),
            )
            contagem[tipo] = contagem.get(tipo, 0) + 1
    for d in payload.get("deleted") or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        prefixo = f"{d.get('type')}|{d['id']}|%"
        for r in con.execute("SELECT dia, tipo FROM hc_registros WHERE chave LIKE ?", (prefixo,)).fetchall():
            if r["tipo"] == "sleep":
                dias_sono.add(r["dia"])
            contagem["deleted"] = contagem.get("deleted", 0) + 1
        con.execute("DELETE FROM hc_registros WHERE chave LIKE ?", (prefixo,))
    con.commit()
    for dia in sorted(dias_sono):
        s = sono_principal(con, dia)
        if s:
            gravar_checkin(con, dia, {"dormiu": s["inicio"][11:16], "sono_h": round(s["dormindo_s"] / 3600, 1)}, "relogio")
    return {"ok": True, "registros": contagem, "dias_sono": sorted(dias_sono)}


def sono_principal(con, dia):
    """Sessão mais longa (>= 3h dormindo) que termina no dia, até as 15h. Cochilos ficam de fora."""
    r = con.execute(
        "SELECT inicio, fim, valor, dados FROM hc_registros WHERE tipo='sleep' AND dia=? "
        "AND substr(fim,12,5)<='15:00' AND valor>=10800 ORDER BY valor DESC LIMIT 1", (dia,)
    ).fetchone()
    if not r:
        return None
    d = json.loads(r["dados"])
    return {"inicio": r["inicio"], "fim": r["fim"], "dormindo_s": int(r["valor"]),
            "fases": d.get("fases", {}), "estagios": d.get("estagios", [])}


def resumo_dias(con, inicio, fim, com_estagios_de=None):
    """Resumo diário de saúde entre as datas (AAAA-MM-DD, inclusivas)."""
    preparar(con)
    out = {}

    def dia(d):
        return out.setdefault(d, {"data": d})

    for r in con.execute(
        "SELECT tipo, dia, SUM(valor) s, COUNT(*) n, MIN(valor) mi, MAX(valor) ma, AVG(valor) av "
        "FROM hc_registros WHERE dia BETWEEN ? AND ? AND tipo IN "
        "('steps','distance','active_calories','heart_rate','resting_heart_rate','oxygen_saturation',"
        "'heart_rate_variability','respiratory_rate') GROUP BY tipo, dia", (inicio, fim)
    ):
        x = dia(r["dia"])
        t = r["tipo"]
        if t == "steps":
            x["passos"] = int(r["s"] or 0)
        elif t == "distance":
            x["km"] = round((r["s"] or 0) / 1000, 2)
        elif t == "active_calories":
            x["kcal_ativas"] = round(r["s"] or 0)
        elif t == "heart_rate":
            x["fc"] = {"min": r["mi"], "max": r["ma"], "media": round(r["av"] or 0)}
        elif t == "resting_heart_rate":
            x["fc_repouso"] = round(r["av"] or 0)
        elif t == "oxygen_saturation":
            x["spo2"] = round(r["av"] or 0, 1)
            x["spo2_min"] = r["mi"]
        elif t == "heart_rate_variability":
            x["hrv"] = round(r["av"] or 0)
        elif t == "respiratory_rate":
            x["resp"] = round(r["av"] or 0, 1)
    # FC mínima real (o agregado guarda min por bucket dentro de `dados`)
    for r in con.execute(
        "SELECT dia, dados FROM hc_registros WHERE tipo='heart_rate' AND dia BETWEEN ? AND ?", (inicio, fim)
    ):
        d = json.loads(r["dados"])
        x = dia(r["dia"]).setdefault("fc", {})
        if isinstance(d.get("min"), (int, float)):
            x["min"] = min(x.get("min") or 999, d["min"])
        if isinstance(d.get("max"), (int, float)):
            x["max"] = max(x.get("max") or 0, d["max"])
    for r in con.execute(
        "SELECT dia, inicio, fim, valor, dados FROM hc_registros WHERE tipo='exercise' AND dia BETWEEN ? AND ? "
        "ORDER BY inicio", (inicio, fim)
    ):
        d = json.loads(r["dados"])
        dia(r["dia"]).setdefault("treinos", []).append(
            {"inicio": r["inicio"][11:16], "min": round((r["valor"] or 0) / 60), "tipo": d.get("type"),
             "passos": d.get("steps"), "km": round(d["distance_meters"] / 1000, 2) if d.get("distance_meters") else None})
    # Sem sessão de treino no Health Connect? Alguns apps (ex.: Mi Fitness) só gravam FC durante treinos:
    # blocos contínuos de FC (buracos <= 5 min, >= 15 min) viram "treino detectado pela FC".
    por_dia = {}
    for r in con.execute(
        "SELECT dia, inicio, valor FROM hc_registros WHERE tipo='heart_rate' AND dia BETWEEN ? AND ? ORDER BY inicio",
        (inicio, fim)
    ):
        por_dia.setdefault(r["dia"], []).append((datetime.fromisoformat(r["inicio"]), r["valor"]))
    for d, pts in por_dia.items():
        if out.get(d, {}).get("treinos"):
            continue
        blocos, atual = [], [pts[0]]
        for p in pts[1:]:
            if p[0] - atual[-1][0] <= timedelta(minutes=5):
                atual.append(p)
            else:
                blocos.append(atual)
                atual = [p]
        blocos.append(atual)
        for b in blocos:
            minutos = round((b[-1][0] - b[0][0]).total_seconds() / 60) + 1
            if minutos >= 15:
                vals = [v for _, v in b if v]
                dia(d).setdefault("treinos", []).append(
                    {"inicio": b[0][0].strftime("%H:%M"), "min": minutos, "tipo": "fc",
                     "fc_media": round(sum(vals) / len(vals)) if vals else None})
    for r in con.execute(
        "SELECT dia, valor FROM hc_registros WHERE tipo='weight' AND dia BETWEEN ? AND ? ORDER BY inicio", (inicio, fim)
    ):
        dia(r["dia"])["peso"] = round(r["valor"], 1)
    d0 = datetime.fromisoformat(inicio).date()
    d1 = datetime.fromisoformat(fim).date()
    while d0 <= d1:
        k = d0.isoformat()
        s = sono_principal(con, k)
        if s:
            x = dia(k)
            x["sono"] = {"inicio": s["inicio"][11:16], "fim": s["fim"][11:16],
                         "h": round(s["dormindo_s"] / 3600, 2),
                         "fases": {k2: round(v / 60) for k2, v in s["fases"].items()}}
            if com_estagios_de == k:
                x["sono"]["estagios"] = [
                    {"f": FASES.get(str(e.get("stage")), "desconhecido"),
                     "i": instante(e["start_time"]).strftime("%H:%M"), "m": round((e.get("duration_seconds") or 0) / 60)}
                    for e in s["estagios"]]
        d0 += timedelta(days=1)
    return [out[k] for k in sorted(out)]


def inventario(con):
    """O que chegou do relógio, por tipo: quantidade, período e origem."""
    preparar(con)
    return [dict(r) for r in con.execute(
        "SELECT tipo, COUNT(*) n, MIN(dia) de, MAX(dia) ate, GROUP_CONCAT(DISTINCT origem) origens "
        "FROM hc_registros GROUP BY tipo ORDER BY n DESC")]
