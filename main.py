import calendar
import hashlib
import hmac
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from fastapi import Body, Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).parent
DB = Path(os.getenv("GASTOS_DB", HERE / "data.json"))
DAY = 10  # len("2026-10-25")
CATS = [("super", "Súper"), ("fuera", "Comer fuera"), ("ocio", "Ocio"), ("transporte", "Transporte"),
        ("casa", "Casa"), ("suscripciones", "Suscripciones"), ("ropa", "Ropa"), ("otros", "Otros")]
# Ingreso del ciclo y día de cobro. Sin sueldo fijo: GASTOS_INGRESO=0 y GASTOS_COBRO=1 (meses naturales)
# (meses naturales); con ingreso 0 lo que debería gastar sale de lo que gasta de media, no de un %.
AJUSTES = {"ingreso": float(os.getenv("GASTOS_INGRESO", "1600")), "dia_cobro": int(os.getenv("GASTOS_COBRO", "28"))}
EMPTY = {"cats": [{"id": i, "n": n, "presu": 0} for i, n in CATS], "gastos": [], "ajustes": dict(AJUSTES)}
SRCS = {"web", "atajo", "applepay", "bot", "ticket"}

# Cuánto debería gastar: 80 % en vivir y 20 % de ahorro (la regla 50/30/20 apretada a un
# piso compartido y a la dieta de comida.yagotg.dev). Los fijos se toman de lo que de
# verdad pagas en cuanto hay historial, y el súper del presupuesto semanal de comida.
REPARTO = {"casa": .30, "super": .11, "fuera": .08, "ocio": .07, "transporte": .06,
           "suscripciones": .04, "ropa": .05, "otros": .09}
FIJOS = {"casa", "suscripciones"}   # se pagan de golpe: proyectarlos por días daría disparates
COMIDA_DATA = Path(os.getenv("GASTOS_COMIDA", "/home/pi/comida/data.json"))

# Avisos por Telegram al pasar del 80 % y del 100 % (mismo bot que todo-bot). Sin token, no avisa.
TG_TOKEN = os.getenv("TELEGRAM_TOKEN") or ""
TG_YO = os.getenv("TELEGRAM_USER_ID") or ""

# ---------- puerta ----------
# Igual que todo y comida: sin contraseña la app NO se abre, devuelve 503.
PASS = os.getenv("GASTOS_PASS") or ""
SECRET = (os.getenv("GASTOS_SECRET") or "").encode()
COOKIE = "gastos_sesion"
VIDA = 90 * 24 * 3600

app = FastAPI()
# Un solo uvicorn, pero las rutas síncronas van en hilos: el atajo y la web a la vez se pisarían el leer-modificar-escribir.
cerrojo = threading.Lock()


def firma(exp):
    return hmac.new(SECRET, str(exp).encode(), hashlib.sha256).hexdigest()


def vale(galleta):
    exp, _, sig = str(galleta or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, firma(exp))


def exige(galleta, cabecera):
    if not PASS or not SECRET:
        raise HTTPException(503, "Falta GASTOS_PASS/GASTOS_SECRET en el entorno")
    # las máquinas (atajo, todo-bot) entran por cabecera, no por cookie
    if cabecera and hmac.compare_digest(cabecera.removeprefix("Bearer ").strip(), PASS):
        return
    if not vale(galleta):
        raise HTTPException(401, "No autenticado")


# ---------- limpieza ----------
def lst(v):
    return v if isinstance(v, list) else []


def day(v):
    s = str(v or "")[:DAY]
    try:
        return date.fromisoformat(s).isoformat() if len(s) == DAY else ""
    except ValueError:
        return ""


def real(v, lo, hi):
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def importe(v):
    """'12,50 €', '1.234,56', '12.5', -12.5 -> 12.5. None si no hay un importe razonable.
    Atajos de iOS manda el importe con el formato del iPhone (coma decimal y símbolo)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
    else:
        s = re.sub(r"[^\d,.]", "", str(v or ""))
        if "," in s and "." in s:  # el último separador es el decimal
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif s.count(".") > 1:  # 1.234.567
            s = s.replace(".", "")
        try:
            n = float(s)
        except ValueError:
            return None
    n = round(abs(n), 2)
    return n if 0 < n <= 100000 else None


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


# Por palabra entera, en orden: "uber eats" tiene que ganar a "uber" de transporte.
PISTAS = [
    # solo cuenta donde exista la categoría (no todas las instancias la tienen)
    ("tabaco", {"estanco", "tabaco", "tabacos", "tabacalera", "cigarros", "cigarrillos", "pitillos", "iqos",
                "vaper", "vapeo", "marlboro", "winston", "camel", "chesterfield", "fortuna", "ducados", "lucky strike",
                "papel de liar"}),
    ("fuera", {"uber eats", "just eat", "glovo", "deliveroo", "telepizza", "dominos", "mcdonalds", "burger",
               "kfc", "bar", "restaurante", "cafeteria", "cafe", "cena", "comer", "comida fuera", "cerveza",
               "tapas", "pizzeria", "kebab", "sushi", "100 montaditos", "vips", "starbucks"}),
    ("super", {"mercadona", "dia", "lidl", "alcampo", "carrefour", "eroski", "aldi", "consum", "supermercado",
               "super", "hipercor", "simply", "ahorramas", "bm", "caprabo", "froiz", "gadis", "compra"}),
    ("transporte", {"renfe", "cabify", "uber", "bolt", "taxi", "metro", "bus", "autobus", "tranvia", "tren",
                    "gasolina", "gasolinera", "repsol", "cepsa", "galp", "bp", "parking", "peaje", "blablacar",
                    "alsa", "iryo", "ouigo", "avion", "vueling", "ryanair", "iberia"}),
    ("suscripciones", {"netflix", "spotify", "hbo", "disney", "prime", "youtube", "icloud", "chatgpt", "openai",
                       "claude", "anthropic", "gimnasio", "gym", "suscripcion"}),
    ("ocio", {"cine", "teatro", "concierto", "entradas", "ticketmaster", "steam", "playstation", "nintendo",
              "libro", "libreria", "escalada", "rocodromo", "copas", "discoteca", "museo", "fnac"}),
    ("casa", {"ikea", "leroy", "bricomart", "bauhaus", "alquiler", "luz", "agua", "gas", "internet", "fibra",
              "movistar", "vodafone", "orange", "digi", "iberdrola", "endesa", "naturgy", "ferreteria", "farmacia"}),
    ("ropa", {"zara", "primark", "decathlon", "bershka", "pull", "mango", "hm", "h&m", "uniqlo", "nike",
              "adidas", "shein", "zalando", "vinted", "zapatillas"}),
]


def adivina(texto, cats):
    """Categoría por el comercio o la nota. Si no hay pista, la última categoría (Otros)."""
    t = sin_tildes(texto)
    palabras = set(re.findall(r"[a-z0-9&]+", t))
    ids = [c["id"] for c in cats]
    for cat, pistas in PISTAS:
        if cat in ids and any((p in t) if " " in p else (p in palabras) for p in pistas):
            return cat
    return "otros" if "otros" in ids else ids[-1]


def de_nombre(nombre, cats):
    """El atajo manda el nombre de la lista ('Comer fuera'), no el id."""
    n = sin_tildes(nombre).strip()
    return next((c["id"] for c in cats if n in (c["id"], sin_tildes(c["n"]))), None)


def gasto(g, ids, por_defecto):
    imp, dia = importe(g.get("importe")), day(g.get("dia"))
    if not imp or not dia or not g.get("id"):
        return None
    return {
        "id": str(g["id"])[:40],
        "dia": dia,
        "importe": imp,
        "cat": c if (c := str(g.get("cat") or "")) in ids else por_defecto,
        "nota": str(g.get("nota") or "").strip()[:120],
        "comercio": str(g.get("comercio") or "").strip()[:60],
        "src": s if (s := str(g.get("src") or "")) in SRCS else "web",
        # líneas del ticket; "ing" es el id del ingrediente en comida, si Claude lo reconoció
        "lineas": [
            {"t": str(l.get("t") or "").strip()[:60], "imp": importe(l.get("imp")) or 0,
             "ing": str(l.get("ing") or "")[:40]}
            for l in lst(g.get("lineas"))[:80]
            if isinstance(l, dict) and str(l.get("t") or "").strip()
        ],
    }


def clean(state):
    """Rebuild the state with a fixed shape: anything that reaches the DB goes through here."""
    cats = [
        {"id": str(c["id"])[:24], "n": str(c.get("n") or "").strip()[:40], "presu": real(c.get("presu"), 0, 100000) or 0}
        for c in lst(state.get("cats"))
        if isinstance(c, dict) and c.get("id") and str(c.get("n") or "").strip()
    ][:30] or [dict(c) for c in EMPTY["cats"]]
    ids = {c["id"] for c in cats}
    por_defecto = "otros" if "otros" in ids else cats[-1]["id"]
    vistos, gastos = set(), []
    for g in lst(state.get("gastos"))[-20000:]:
        if isinstance(g, dict) and (x := gasto(g, ids, por_defecto)) and x["id"] not in vistos:
            vistos.add(x["id"])
            gastos.append(x)
    a = state.get("ajustes") if isinstance(state.get("ajustes"), dict) else {}
    try:
        cobro = min(31, max(1, int(a.get("dia_cobro"))))
    except (TypeError, ValueError):
        cobro = AJUSTES["dia_cobro"]
    return {"cats": cats, "gastos": sorted(gastos, key=lambda x: (x["dia"], x["id"])),
            "ajustes": {"ingreso": real(a.get("ingreso"), 0, 1000000) or AJUSTES["ingreso"], "dia_cobro": cobro}}


def lee():
    return clean(json.loads(DB.read_text("utf-8"))) if DB.exists() else clean(EMPTY)


def escribe(estado):
    estado = clean(estado)
    tmp = DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False), "utf-8")
    tmp.replace(DB)  # atómico: un corte de luz a mitad no deja el JSON roto
    return estado


def eur(n):
    return f"{n:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " €"


# ---------- ciclos de cobro ----------
def dia_de(y, m, d):
    """El día d de ese mes, o el último si no lo tiene (cobrar el 31 en febrero)."""
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def mes_mas(y, m, n):
    m0 = y * 12 + m - 1 + n
    return m0 // 12, m0 % 12 + 1


def ciclo(ref, cobro):
    """[inicio, fin] del ciclo de cobro que contiene ref. Cobrando el 28: del 28 al 27."""
    ini = dia_de(ref.year, ref.month, cobro)
    if ini > ref:
        ini = dia_de(*mes_mas(ref.year, ref.month, -1), cobro)
    return ini, dia_de(*mes_mas(ini.year, ini.month, 1), cobro) - timedelta(days=1)


def entre(estado, ini, fin):
    a, b = ini.isoformat(), fin.isoformat()
    return [g for g in estado["gastos"] if a <= g["dia"] <= b]


def suma(gastos, cat=None):
    return round(sum(g["importe"] for g in gastos if cat is None or g["cat"] == cat), 2)


def cinco(n):
    return int(5 * round(n / 5))


def sugeridos(estado, hoy):
    """Cuánto debería gastar en cada categoría, y por qué."""
    ingreso, cobro = estado["ajustes"]["ingreso"], estado["ajustes"]["dia_cobro"]
    pasados, fin = [], ciclo(hoy, cobro)[0] - timedelta(days=1)
    for _ in range(3):  # los tres últimos ciclos completos
        ini, f = ciclo(fin, cobro)
        pasados.append(entre(estado, ini, f))
        fin = ini - timedelta(days=1)
    try:
        semana = float(json.loads(COMIDA_DATA.read_text("utf-8"))["perfil"]["presupuesto"])
    except (OSError, ValueError, KeyError, TypeError):
        semana = 0
    out = {}
    for c in estado["cats"]:
        pct = REPARTO.get(c["id"])
        if pct is None:
            out[c["id"]] = {"importe": 0, "por": "categoría tuya: el límite lo pones tú"}
            continue
        reales = [suma(p, c["id"]) for p in pasados if suma(p, c["id"])]
        if not ingreso:   # sin ingreso fijo no hay porcentaje que valga: la referencia es lo que gasta
            out[c["id"]] = ({"importe": cinco(sum(reales) / len(reales)), "por": "lo que gastas de media al mes"}
                            if reales else {"importe": 0, "por": "aún sin historial: el límite lo pones tú"})
            continue
        imp, por = cinco(ingreso * pct), f"el {round(pct * 100)} % de lo que cobras"
        if c["id"] == "super" and semana:
            imp, por = cinco(semana * 365 / 12 / 7), f"tu presupuesto de comida ({semana:g} € a la semana)"
        if c["id"] in FIJOS and reales:
            imp, por = cinco(sum(reales) / len(reales)), "lo que pagas de media: es un gasto fijo"
        out[c["id"]] = {"importe": imp, "por": por}
    return out


def acumulado(gastos, ini, dias):
    por_dia = {}
    for g in gastos:
        por_dia[g["dia"]] = por_dia.get(g["dia"], 0) + g["importe"]
    total, serie = 0, []
    for i in range(dias):
        total += por_dia.get((ini + timedelta(days=i)).isoformat(), 0)
        serie.append(round(total, 2))
    return serie


def resumen(estado, ref=None, hoy=None):
    """Todo lo del ciclo que contiene ref: cifras, categorías, series para gráficas e insights."""
    hoy = hoy or date.today()
    ref = ref or hoy
    cobro, ingreso = estado["ajustes"]["dia_cobro"], estado["ajustes"]["ingreso"]
    ini, fin = ciclo(ref, cobro)
    dias = (fin - ini).days + 1
    hechos = 0 if hoy < ini else min(dias, (hoy - ini).days + 1)   # días ya vividos del ciclo
    del_ciclo = entre(estado, ini, fin)
    pini, pfin = ciclo(ini - timedelta(days=1), cobro)
    previo = entre(estado, pini, pfin)
    serie_previa = acumulado(previo, pini, (pfin - pini).days + 1)
    sug = sugeridos(estado, hoy)
    frac = hechos / dias

    cats = []
    for c in estado["cats"]:
        g = suma(del_ciclo, c["id"])
        proy = g if (c["id"] in FIJOS or not frac or hechos == dias) else g / frac
        estado_c = ("pasado" if c["presu"] and g > c["presu"] else
                    "ojo" if c["presu"] and hechos >= 3 and proy > c["presu"] * 1.05 else "ok")
        cats.append({**c, "gastado": g, "proyeccion": round(proy, 2), "estado": estado_c,
                     "anterior": suma(previo, c["id"]), "sugerido": sug[c["id"]]["importe"],
                     "por": sug[c["id"]]["por"]})

    historico, f = [], fin
    for _ in range(6):
        i, ff = ciclo(f, cobro)
        historico.append({"inicio": i.isoformat(), "fin": ff.isoformat(), "total": suma(entre(estado, i, ff))})
        f = i - timedelta(days=1)
    historico.reverse()

    ayer = (hoy - timedelta(days=1)).isoformat()
    r = {
        "inicio": ini.isoformat(), "fin": fin.isoformat(), "dias": dias, "hechos": hechos,
        "actual": ini <= hoy <= fin,
        "total": suma(del_ciclo),
        "presu": round(sum(c["presu"] for c in estado["cats"]), 2),
        "ingreso": ingreso, "dia_cobro": cobro,
        "proyeccion": round(sum(c["proyeccion"] for c in cats), 2),
        "anterior_a_esta_altura": serie_previa[min(hechos, len(serie_previa)) - 1] if hechos and serie_previa else 0,
        "cats": cats,
        "ayer": suma([g for g in estado["gastos"] if g["dia"] == ayer]),
        "n": len(del_ciclo),
        "serie": acumulado(del_ciclo, ini, dias)[:hechos],
        "serie_previa": serie_previa,
        "historico": historico,
        "sugerido_total": sum(s["importe"] for s in sug.values()),
    }
    r["insights"] = insights(r, del_ciclo, hoy)
    return r


def insights(r, del_ciclo, hoy):
    """Frases cortas, de lo más grave a lo más curioso. Las usan la web, el bot y el resumen."""
    out = []
    fin = date.fromisoformat(r["fin"])
    quedan = (fin - hoy).days + 1 if r["actual"] else 0
    for c in r["cats"]:
        if c["estado"] == "pasado":
            out.append(("mal", f"Te has pasado en {c['n']}: {eur(c['gastado'])} de {eur(c['presu'])} "
                               f"(+{eur(c['gastado'] - c['presu'])})."))
    for c in r["cats"]:
        if c["estado"] == "ojo":
            out.append(("ojo", f"{c['n']} va camino de {eur(c['proyeccion'])} y tu límite es {eur(c['presu'])}: "
                               f"te quedan {eur(max(0, c['presu'] - c['gastado']))} para {quedan} días."))
    if not r["presu"]:
        out.append(("info", "Aún no tienes presupuestos. "
                    + (f"Pulsa «Presupuestos» → «Usar sugeridos»: {eur(r['sugerido_total'])} al ciclo y ahorrarías "
                       f"{eur(r['ingreso'] - r['sugerido_total'])}." if r["ingreso"] else
                       f"Pulsa «Presupuestos» → «Usar sugeridos»: lo que gastas de media, {eur(r['sugerido_total'])} al mes."
                       if r["sugerido_total"] else
                       "Cuando lleves un mes apuntando te sugiero límites con lo que gastas; o ponlos tú en «Presupuestos».")))
    elif r["actual"]:
        resto = r["presu"] - r["total"]
        # habla del total: con una categoría pasada puede seguir habiendo margen en el conjunto
        out.append(("ok", f"En el total del ciclo te quedan {eur(resto)}: {eur(resto / quedan)} al día hasta el {fin.day}.")
                   if resto > 0 else ("mal", "Ya has gastado todo el presupuesto de este ciclo."))
    if r["actual"] and r["hechos"] >= 3 and r["ingreso"]:
        ahorro = r["ingreso"] - r["proyeccion"]
        pct = round(ahorro * 100 / r["ingreso"])
        out.append(("ok" if pct >= 20 else "ojo" if pct >= 0 else "mal",
                    f"A este ritmo cerrarás el ciclo en {eur(r['proyeccion'])}"
                    + (f" y ahorrarás {eur(ahorro)} ({pct} %)." if ahorro >= 0 else f": {eur(-ahorro)} más de lo que cobras.")))
    if r["actual"] and r["anterior_a_esta_altura"] and r["hechos"]:
        dif = r["total"] - r["anterior_a_esta_altura"]
        pct = round(dif * 100 / r["anterior_a_esta_altura"])
        if abs(pct) >= 5:
            mayor = max(r["cats"], key=lambda c: c["gastado"] - c["anterior"])
            extra = f", sobre todo en {mayor['n']}" if dif > 0 and mayor["gastado"] > mayor["anterior"] else ""
            out.append(("ojo" if pct > 15 else "ok" if pct < 0 else "info",
                        f"Llevas un {abs(pct)} % {'más' if dif > 0 else 'menos'} que el ciclo pasado a estas alturas{extra}."))
    if del_ciclo:
        g = max(del_ciclo, key=lambda g: g["importe"])
        donde = g["comercio"] or g["nota"] or "sin nota"
        out.append(("info", f"El gasto más grande: {eur(g['importe'])} en {donde} ({int(g['dia'][8:])}/{int(g['dia'][5:7])})."))
        veces = {}
        for x in del_ciclo:
            if x["comercio"]:
                n, t = veces.get(x["comercio"], (0, 0))
                veces[x["comercio"]] = (n + 1, t + x["importe"])
        if veces:
            com, (n, t) = max(veces.items(), key=lambda kv: kv[1][1])
            if n >= 2:
                out.append(("info", f"Donde más gastas: {com}, {n} veces y {eur(t)}."))
    orden = {"mal": 0, "ojo": 1, "ok": 2, "info": 3}
    return [{"nivel": n, "texto": t} for n, t in sorted(out, key=lambda x: orden[x[0]])][:7]


def avisos(antes, despues, g):
    """Lo que cruza el 80 % o el 100 % con este gasto, en el ciclo en curso. Una vez por cruce."""
    if not despues["actual"]:
        return []
    out = []
    c0 = next(c for c in antes["cats"] if c["id"] == g["cat"])
    c1 = next(c for c in despues["cats"] if c["id"] == g["cat"])
    p = c1["presu"]
    quedan = (date.fromisoformat(despues["fin"]) - date.today()).days + 1
    if p and c0["gastado"] <= p < c1["gastado"]:
        out.append(f"🔴 Te has pasado en {c1['n']}: {eur(c1['gastado'])} de {eur(p)}.")
    elif p and c0["gastado"] < .8 * p <= c1["gastado"]:
        out.append(f"🟡 Llevas el {round(c1['gastado'] * 100 / p)} % de {c1['n']}: "
                   f"te quedan {eur(p - c1['gastado'])} para {quedan} días.")
    tp = despues["presu"]
    if tp and antes["total"] <= tp < despues["total"]:
        out.append(f"🔴 Te has pasado del presupuesto del ciclo: {eur(despues['total'])} de {eur(tp)}.")
    return out


def telegram(texto):
    if not (TG_TOKEN and TG_YO):
        return

    def manda():
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                         json.dumps({"chat_id": int(TG_YO), "text": texto}).encode(),
                                         {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=20).close()
        except Exception as e:  # sin Telegram el gasto se apunta igual
            print("telegram:", e, flush=True)
    threading.Thread(target=manda, daemon=True).start()


# ---------- rutas ----------
@app.post("/api/login")
def login(response: Response, request: Request, datos: dict = Body(...)):
    if not PASS or not SECRET:
        raise HTTPException(503, "Falta GASTOS_PASS/GASTOS_SECRET en el entorno")
    if not hmac.compare_digest(str(datos.get("pass") or ""), PASS):
        raise HTTPException(401, "Contraseña incorrecta")
    exp = int(time.time()) + VIDA
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, f"{exp}.{firma(exp)}", max_age=VIDA,
                        httponly=True, samesite="lax", secure=https, path="/")
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/estado")
def get_estado(gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    exige(gastos_sesion, authorization)
    return lee()


@app.put("/api/estado")
def put_estado(estado: dict, gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    exige(gastos_sesion, authorization)
    with cerrojo:
        return escribe(estado)


@app.get("/api/resumen")
def get_resumen(dia: str = "", gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """El ciclo de cobro que contiene `dia` (por defecto, hoy)."""
    exige(gastos_sesion, authorization)
    return resumen(lee(), date.fromisoformat(day(dia)) if day(dia) else None)


# ---------- apuntar un gasto de una sola llamada ----------
# Para el atajo de iOS (y Apple Pay) y para todo-bot: no pueden hacer el leer-modificar-escribir
# del PUT entero, así que esto lo hace todo y devuelve ya el texto de la notificación.
@app.post("/api/gasto")
def apunta(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    exige(gastos_sesion, authorization)
    imp = importe(a.get("importe"))
    if not imp:
        # el mensaje se lee en la notificación del móvil: que diga qué hacer
        raise HTTPException(400, f"«{a.get('importe')}» no es un importe: en el atajo, «importe» tiene que ser "
                                 "la variable del número que has escrito (o el Importe de la transacción)")
    with cerrojo:
        estado = lee()
        comercio, nota = str(a.get("comercio") or "").strip(), str(a.get("nota") or "").strip()
        cat = de_nombre(a.get("cat"), estado["cats"]) or adivina(f"{comercio} {nota} {a.get('cat') or ''}", estado["cats"])
        dia = day(a.get("dia")) or date.today().isoformat()
        g = {"id": str(a.get("id") or "")[:40] or f"{dia}-{time.time_ns() % 10**9}", "dia": dia, "importe": imp,
             "cat": cat, "nota": nota, "comercio": comercio, "src": a.get("src") or "atajo", "lineas": a.get("lineas")}
        antes = resumen(estado, date.fromisoformat(dia))
        # mismo id dos veces = el atajo se disparó repetido: se reemplaza, no se duplica
        estado["gastos"] = [x for x in estado["gastos"] if x["id"] != g["id"]] + [g]
        estado = escribe(estado)
    g = next(x for x in estado["gastos"] if x["id"] == g["id"])
    r = resumen(estado, date.fromisoformat(g["dia"]))
    c = next(x for x in r["cats"] if x["id"] == g["cat"])
    donde = f" · {g['comercio']}" if g["comercio"] else (f" · {g['nota']}" if g["nota"] else "")
    texto = f"{eur(g['importe'])} en {c['n']}{donde}\nEste ciclo: {eur(r['total'])}"
    if c["presu"]:
        texto += f" · {c['n']}: {eur(c['gastado'])} de {eur(c['presu'])}"
    alertas = avisos(antes, r, g)
    if alertas:
        texto += "\n" + "\n".join(alertas)
        # lo que entra por el bot ya contesta en Telegram con este texto: no avisar dos veces
        if g["src"] not in ("bot", "ticket"):
            telegram("\n".join(alertas))
    return {"texto": texto, "gasto": g, "avisos": alertas}


# Otra persona con su propia instancia (su carpeta, su .env y otro puerto) pone su nombre en la
# página; mismo código y mismo index.html, datos y contraseña aparte.
NOMBRE = os.getenv("GASTOS_NOMBRE") or ""


def con_nombre(html, nombre):
    if not nombre:
        return html
    return (html.replace("<h1>Gastos</h1>", f"<h1>Gastos · {nombre}</h1>", 1)
                .replace("<title>Gastos</title>", f"<title>Gastos · {nombre}</title>", 1)
                .replace('content="Gastos"', f'content="Gastos {nombre}"', 1))


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def portada():
    return con_nombre((HERE / "static" / "index.html").read_text("utf-8"), NOMBRE)


# El estático queda abierto: no lleva datos, y así la web puede pintar la puerta cuando la API da 401.
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
