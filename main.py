import calendar
import hashlib
import hmac
import json
import math
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
EMPTY = {"cats": [{"id": i, "n": n, "presu": 0} for i, n in CATS], "gastos": [], "ajustes": dict(AJUSTES),
         "reglas": [], "rechazadas": [], "recurrentes": {}}
SRCS = {"web", "atajo", "applepay", "bot", "ticket", "banco", "siri", "correo"}

# Cuánto debería gastar: 80 % en vivir y 20 % de ahorro (la regla 50/30/20 apretada a un
# piso compartido). Los fijos se toman de lo que de verdad pagas en cuanto hay historial.
REPARTO = {"casa": .30, "super": .11, "fuera": .08, "ocio": .07, "transporte": .06,
           "suscripciones": .04, "ropa": .05, "otros": .09}
FIJOS = {"casa", "suscripciones"}   # se pagan de golpe: proyectarlos por días daría disparates

# Avisos por Telegram al pasar del 80 % y del 100 % (mismo bot que todo-bot). Sin token, no avisa.
TG_TOKEN = os.getenv("TELEGRAM_TOKEN") or ""
TG_YO = os.getenv("TELEGRAM_USER_ID") or ""

# ---------- puerta ----------
# Igual que todo: sin contraseña la app NO se abre, devuelve 503.
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


# ---------- viajes ----------
# Un viaje va aparte: sus gastos no cuentan en el ciclo ni en los presupuestos de categoría (un Airbnb
# no es «ocio de noviembre»). Los paga la hucha de viajes, que se llena cada ciclo y puede quedarse en
# negativo si un viaje se paga de golpe: los ciclos siguientes la devuelven a cero.
PISTAS_VIAJE = {"booking", "airbnb", "hotel", "hostal", "vuelo", "vuelos", "ryanair", "vueling", "iberia", "easyjet",
                "aeropuerto", "aena", "expedia", "skyscanner", "edreams", "wizz", "transavia", "kiwi", "lastminute"}


def palabras(s):
    return set(re.findall(r"[a-z0-9&]+", sin_tildes(s)))


def que_viaje(g, viajes):
    """El viaje de un gasto: el que nombra la nota («vuelos Londres»), el que está en curso ese día (salvo
    fijos) o, si es una reserva (Booking, vuelos...), el único que viene por delante. "" si ninguno."""
    texto = palabras(f"{g['comercio']} {g['nota']}")
    for v in viajes:
        if {w for w in palabras(v["n"]) if len(w) >= 4} & texto:
            return v["id"]
    for v in viajes:
        if v["desde"] <= g["dia"] <= v["hasta"] and g["cat"] not in FIJOS:
            return v["id"]
    if texto & PISTAS_VIAJE and g["cat"] != "super":   # «kiwi» en el súper es fruta
        por_delante = [v for v in viajes if g["dia"] <= v["hasta"]
                       and (date.fromisoformat(v["desde"]) - timedelta(days=180)).isoformat() <= g["dia"]]
        if len(por_delante) == 1:
            return por_delante[0]["id"]
    return ""


def de_viaje(nombre, viajes):
    """El viaje que dice quien apunta, por id o por nombre. Otra cosa («no») = ninguno."""
    n = sin_tildes(nombre).strip()
    return next((v["id"] for v in viajes if n in (v["id"], sin_tildes(v["n"]))), "")


def aviso_viaje(v, antes, despues):
    p = v["presu"]
    if p and antes <= p < despues:
        return [f"🔴 Te has pasado en el viaje {v['n']}: {eur(despues)} de {eur(p)}."]
    if p and antes < .8 * p <= despues:
        return [f"🟡 Llevas el {round(despues * 100 / p)} % del viaje {v['n']}: quedan {eur(p - despues)}."]
    return []


# ---------- viajes compartidos y en otra moneda ----------
# Dos instancias (una pareja), cada una con sus datos. Un viaje «con» la pareja sale en las dos: cada app
# lee de la otra (del mismo disco, solo lectura) los gastos de ESE viaje, para las cuentas. Cada uno apunta
# lo que paga; el reparto de cada gasto dice de quién es.
PAREJA = os.getenv("GASTOS_PAREJA") or ""
PAREJA_DB = Path(os.getenv("GASTOS_PAREJA_DB") or "/no/existe")
# Inversiones de todo (inversiones.json, solo lectura): lo comprado en cada ciclo cuenta contra el presupuesto de inversión.
# Sin la variable (otra instancia), el presupuesto vale igual pero lo aportado no se sabe.
INVERSIONES = Path(os.getenv("GASTOS_INVERSIONES") or "/no/existe")
# Multas por hábitos fallados (multas.json de todo): suman a lo que toca invertir ese ciclo.
MULTAS = Path(os.getenv("GASTOS_MULTAS") or "/no/existe")
REPARTOS = {"medias", "mio", "suyo", "pago", "cobro"}   # pago: le pago a la pareja para saldar; cobro: me paga
MONEDAS = {"EUR": "€", "GBP": "£", "USD": "$", "CHF": "CHF", "SEK": "kr", "NOK": "kr", "DKK": "kr", "CZK": "Kč",
           "PLN": "zł", "HUF": "Ft", "JPY": "¥", "MAD": "DH"}


def moneda_de(v):
    """La moneda que dice el importe («£12,50», «12.50 GBP», «12,50 €»); "" si no dice ninguna."""
    s = str(v or "").upper()
    return (next((c for c in MONEDAS if re.search(rf"\b{c}\b", s)), "")
            or {"€": "EUR", "£": "GBP", "$": "USD", "¥": "JPY"}.get(next((ch for ch in s if ch in "€£$¥"), ""), ""))


def en_moneda(n, m):
    return eur(n)[:-1] + MONEDAS.get(m, m)


def tasa(v):
    """Euros por unidad, con los decimales que hagan falta (el yen va por 0,0057)."""
    try:
        n = round(float(str(v).replace(",", ".")), 5)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n < 100000 else 0


def cambio_de(moneda):
    """El cambio de hoy del BCE (frankfurter.dev). 0 si no responde: entonces se pone a mano."""
    try:
        with urllib.request.urlopen(f"https://api.frankfurter.dev/v1/latest?base={moneda}&symbols=EUR", timeout=8) as r:
            return tasa(json.load(r)["rates"]["EUR"])
    except Exception:
        return 0


def de_la_pareja():
    """Los datos de la pareja, para los viajes compartidos. None si no hay pareja o no se pueden leer."""
    try:
        return clean(json.loads(PAREJA_DB.read_text("utf-8"))) if PAREJA else None
    except (OSError, ValueError):
        return None


def mi_parte(g, mio, compartido):
    """De un gasto de viaje, lo que me toca a mí (mio: si lo apunté yo). Es lo que cuenta en la hucha."""
    if not compartido:
        return g["importe"] if mio else 0
    r = g["reparto"]
    if r in ("pago", "cobro"):
        return 0
    return g["importe"] / 2 if r == "medias" else g["importe"] if (r == "mio") == mio else 0


def me_debe(g, mio):
    """Lo que, por este gasto, la pareja me debe (negativo: lo que le debo yo)."""
    x = g["importe"]
    d = {"medias": x / 2, "suyo": x, "mio": 0, "pago": x, "cobro": -x}[g["reparto"]]
    return d if mio else -d


def cuentas(v, estado, pareja):
    """Las de un viaje: el total, lo que ha pagado cada uno, mi parte y lo que la pareja me debe. Sin compartir, todo es mío."""
    mios = [g for g in estado["gastos"] if g["viaje"] == v["id"]]
    suyos = [g for g in (pareja or {}).get("gastos", []) if g["viaje"] == v["id"]] if v["con"] else []
    pagado = lambda l: round(sum(g["importe"] for g in l if not v["con"] or g["reparto"] not in ("pago", "cobro")), 2)
    return {"total": round(pagado(mios) + pagado(suyos), 2), "pagado": pagado(mios), "pagado_pareja": pagado(suyos),
            "parte": round(sum(mi_parte(g, True, v["con"]) for g in mios) + sum(mi_parte(g, False, True) for g in suyos), 2),
            "me_debe": round(sum(me_debe(g, True) for g in mios) + sum(me_debe(g, False) for g in suyos), 2) if v["con"] else 0,
            "suyos": suyos}


def cuentas_de(estado):
    pareja = de_la_pareja() if any(v["con"] for v in estado["viajes"]) else None
    return {v["id"]: cuentas(v, estado, pareja) for v in estado["viajes"]}


def estimado(estado, g):
    """Lo apuntado en otra moneda (con el cambio del viaje) que es este cargo del banco: a ±3 días y a menos
    de un 5 % (o 1 €), por la diferencia de cambio y la comisión. Se corrige en vez de duplicarse."""
    d = date.fromisoformat(g["dia"])
    c = [x for x in estado["gastos"] if x["moneda"] and x["src"] != "banco"
         and abs(x["importe"] - g["importe"]) <= max(1, .05 * g["importe"]) and abs((date.fromisoformat(x["dia"]) - d).days) <= 3]
    return min(c, key=lambda x: abs(x["importe"] - g["importe"]), default=None)


def gasto(g, ids, por_defecto, vids=()):
    imp, dia = importe(g.get("importe")), day(g.get("dia"))
    if not imp or not dia or not g.get("id"):
        return None
    orig = real(g.get("orig"), 0, 1000000) or 0
    return {
        "id": str(g["id"])[:40],
        "dia": dia,
        "importe": imp,
        "cat": c if (c := str(g.get("cat") or "")) in ids else por_defecto,
        "nota": str(g.get("nota") or "").strip()[:120],
        "comercio": str(g.get("comercio") or "").strip()[:60],
        "src": s if (s := str(g.get("src") or "")) in SRCS else "web",
        "viaje": v if (v := str(g.get("viaje") or "")) in vids else "",   # un viaje borrado lo devuelve al ciclo
        "reparto": r if (r := str(g.get("reparto") or "")) in REPARTOS else "medias",   # solo cuenta en viajes compartidos
        # pagado en otra moneda: lo de verdad (orig) y en qué; "importe" sigue siendo en euros
        "orig": orig, "moneda": (m if (m := str(g.get("moneda") or "").upper()) in MONEDAS else "") if orig else "",
        # líneas del ticket; "ing" quedó de cuando existía comida (borrada el 16/11)
        "lineas": [
            {"t": str(l.get("t") or "").strip()[:60], "imp": importe(l.get("imp")) or 0,
             "ing": str(l.get("ing") or "")[:40]}
            for l in lst(g.get("lineas"))[:80]
            if isinstance(l, dict) and str(l.get("t") or "").strip()
        ],
    }


def ingreso(x, ids, por_defecto):
    """Dinero que entra aparte del sueldo. tipo «extra»: te lo dan (familia, un regalo, una venta) y suma a lo del
    ciclo. «devuelve»: te pagan su parte de algo que pagaste tú, y resta del gasto de su categoría."""
    imp, dia = importe(x.get("importe")), day(x.get("dia"))
    if not imp or not dia or not x.get("id"):
        return None
    tipo = "devuelve" if x.get("tipo") == "devuelve" else "extra"
    return {"id": str(x["id"])[:40], "dia": dia, "importe": imp, "tipo": tipo,
            "cat": (c if (c := str(x.get("cat") or "")) in ids else por_defecto) if tipo == "devuelve" else "",
            "nota": str(x.get("nota") or "").strip()[:120], "comercio": str(x.get("comercio") or "").strip()[:60],
            "src": s if (s := str(x.get("src") or "")) in SRCS else "web"}


def clean(state):
    """Rebuild the state with a fixed shape: anything that reaches the DB goes through here."""
    cats = [
        {"id": str(c["id"])[:24], "n": str(c.get("n") or "").strip()[:40], "presu": real(c.get("presu"), 0, 100000) or 0}
        for c in lst(state.get("cats"))
        if isinstance(c, dict) and c.get("id") and str(c.get("n") or "").strip()
    ][:30] or [dict(c) for c in EMPTY["cats"]]
    ids = {c["id"] for c in cats}
    por_defecto = "otros" if "otros" in ids else cats[-1]["id"]
    viajes = []
    for v in lst(state.get("viajes"))[:200]:
        if isinstance(v, dict) and v.get("id") and str(v.get("n") or "").strip() and day(v.get("desde")) and day(v.get("hasta")):
            desde, hasta = sorted((day(v["desde"]), day(v["hasta"])))
            viajes.append({"id": str(v["id"])[:24], "n": str(v["n"]).strip()[:40], "desde": desde, "hasta": hasta,
                           "presu": real(v.get("presu"), 0, 1000000) or 0,
                           "moneda": m if (m := str(v.get("moneda") or "EUR").upper()) in MONEDAS else "EUR",
                           "cambio": tasa(v.get("cambio")),   # euros por unidad; 0 = sin poner
                           "con": bool(v.get("con"))})        # compartido con la pareja
    vids = {v["id"] for v in viajes}
    vistos, gastos = set(), []
    for g in lst(state.get("gastos"))[-20000:]:
        if isinstance(g, dict) and (x := gasto(g, ids, por_defecto, vids)) and x["id"] not in vistos:
            vistos.add(x["id"])
            gastos.append(x)
    vistos, ingresos = set(), []
    for x in lst(state.get("ingresos"))[-5000:]:
        if isinstance(x, dict) and (i := ingreso(x, ids, por_defecto)) and i["id"] not in vistos:
            vistos.add(i["id"])
            ingresos.append(i)
    a = state.get("ajustes") if isinstance(state.get("ajustes"), dict) else {}
    try:
        cobro = min(31, max(1, int(a.get("dia_cobro"))))
    except (TypeError, ValueError):
        cobro = AJUSTES["dia_cobro"]
    hucha = real(a.get("hucha"), 0, 100000) or 0
    inversion = real(a.get("inversion"), 0, 100000) or 0
    # reglas de categoría (las acepta el usuario; el orden es la prioridad) y lo que ya dijo que no
    vistos, reglas = set(), []
    for r in lst(state.get("reglas"))[:200]:
        if isinstance(r, dict) and (t := norma(r.get("txt"))[:40]) and str(r.get("cat") or "") in ids and t not in vistos:
            vistos.add(t)
            reglas.append({"id": str(r.get("id") or "")[:24] or "r" + hashlib.md5(t.encode()).hexdigest()[:8],
                           "txt": t, "cat": str(r["cat"])})
    rechazadas = list(dict.fromkeys(t for x in lst(state.get("rechazadas"))[-500:] if (t := norma(x)[:40])))
    marcas = state.get("recurrentes") if isinstance(state.get("recurrentes"), dict) else {}
    return {"cats": cats, "gastos": sorted(gastos, key=lambda x: (x["dia"], x["id"])), "viajes": viajes,
            "ingresos": sorted(ingresos, key=lambda x: (x["dia"], x["id"])),
            "ajustes": {"ingreso": real(a.get("ingreso"), 0, 1000000) or AJUSTES["ingreso"], "dia_cobro": cobro,
                        # cuánto se aparta cada ciclo para viajes, y desde cuándo (0 = sin hucha)
                        "hucha": hucha, "hucha_desde": (day(a.get("hucha_desde")) or date.today().isoformat()) if hucha else "",
                        # lo que se dedica a invertir cada ciclo, desde cuándo (0 = sin presupuesto de inversión)
                        "inversion": inversion,
                        "inversion_desde": (day(a.get("inversion_desde")) or date.today().isoformat()) if inversion else ""},
            "reglas": reglas, "rechazadas": rechazadas,
            # recurrentes que el usuario confirmó (si) o ignoró (no), por clave_cargo()
            "recurrentes": {str(k)[:60]: v for k, v in list(marcas.items())[:500] if v in ("si", "no") and str(k).strip()}}


def lee():
    estado = clean(json.loads(DB.read_text("utf-8"))) if DB.exists() else clean(EMPTY)
    # los viajes que la pareja comparte conmigo y aún no tengo, con su mismo id: así mis gastos de esos días van a él.
    # Se guardan en cuanto se escribe algo. ponytail: si la pareja cambia luego las fechas, aquí se quedan las de antes
    if p := de_la_pareja():
        mios = {v["id"] for v in estado["viajes"]}
        estado["viajes"] += [v for v in p["viajes"] if v["con"] and v["id"] not in mios]
    return estado


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


def aparte_en(estado, ini):
    """Lo que el ciclo que empieza en ini aparta para viajes: un fijo más del ciclo, desde que hay hucha."""
    a = estado["ajustes"]
    return a["hucha"] if a["hucha"] and ini >= ciclo(date.fromisoformat(a["hucha_desde"]), a["dia_cobro"])[0] else 0


def aportado(ini, fin):
    """Lo metido en inversiones (compras menos ventas, con comisiones) entre ini y fin. None si no hay de dónde leerlo."""
    try:
        ops = json.loads(INVERSIONES.read_text("utf-8")).get("operaciones") or []
    except (OSError, ValueError, AttributeError):
        return None
    total = 0.0
    for o in ops:
        if not isinstance(o, dict) or not (ini.isoformat() <= str(o.get("fecha"))[:10] <= fin.isoformat()):
            continue
        try:
            bruto = float(o.get("cantidad") or 0) * float(o.get("precio") or 0)
            com = float(o.get("comision") or 0)
        except (TypeError, ValueError):
            continue
        total += bruto + com if o.get("tipo") == "compra" else -(bruto - com) if o.get("tipo") == "venta" else 0
    return round(total, 2)


def multas_en(ini, fin):
    """(euros, lista) de las multas de hábitos entre ini y fin; (0, []) si no hay de dónde leerlas."""
    try:
        l = [m for m in json.loads(MULTAS.read_text("utf-8")).get("multas") or []
             if isinstance(m, dict) and ini.isoformat() <= str(m.get("dia")) <= fin.isoformat()]
        return round(sum(float(m.get("euros") or 0) for m in l), 2), l
    except (OSError, ValueError, AttributeError, TypeError):
        return 0, []


def invertido_en(estado, ini):
    """Lo que el ciclo que empieza en ini dedica a invertir: el presupuesto, o lo aportado si fue más. Un fijo del ciclo,
    como la hucha: el dinero sale de la cuenta aunque no sea un gasto."""
    a = estado["ajustes"]
    if not a["inversion"] or ini < ciclo(date.fromisoformat(a["inversion_desde"]), a["dia_cobro"])[0]:
        return 0
    fin = ciclo(ini, a["dia_cobro"])[1]
    return max(a["inversion"] + multas_en(ini, fin)[0], aportado(ini, fin) or 0)


def fijos_en(estado, ini):
    return round(aparte_en(estado, ini) + invertido_en(estado, ini), 2)


def hucha(estado, hoy):
    """La hucha ciclo a ciclo, desde el primero: lo que se aparta, lo que se fue en viajes y cómo queda.
    Sigue por los ciclos que vienen hasta que vuelve a cero: así se ve cómo se «gana» un viaje pagado de golpe."""
    a = estado["ajustes"]
    if not a["hucha"]:
        return None
    # lo que cuenta es mi parte: en un viaje compartido, la mitad de lo de los dos (o lo que diga cada reparto)
    con = {v["id"] for v in estado["viajes"] if v["con"]}
    partes = [(g["dia"], mi_parte(g, True, g["viaje"] in con)) for g in estado["gastos"] if g["viaje"]]
    partes += [(g["dia"], mi_parte(g, False, True)) for g in ((de_la_pareja() or {}).get("gastos", []) if con else []) if g["viaje"] in con]
    # ponytail: la aportación de ahora cuenta en todos los ciclos pasados; si cambia a menudo, guardar lo aportado ciclo a ciclo
    plan, saldo, i = [], 0, ciclo(date.fromisoformat(a["hucha_desde"]), a["dia_cobro"])[0]
    while len(plan) < 24 and (i <= hoy or saldo < 0):
        f = ciclo(i, a["dia_cobro"])[1]
        gastado = round(sum(x for d, x in partes if i.isoformat() <= d <= f.isoformat()), 2)
        saldo = round(saldo + a["hucha"] - gastado, 2)
        plan.append({"inicio": i.isoformat(), "fin": f.isoformat(), "aparta": a["hucha"], "gastado": gastado,
                     "saldo": saldo, "futuro": i > hoy})
        i = f + timedelta(days=1)
    hechos = [p for p in plan if not p["futuro"]]
    return {"aporte": a["hucha"], "ciclos": len(hechos), "aportado": round(len(hechos) * a["hucha"], 2),
            "gastado": round(sum(p["gastado"] for p in hechos), 2), "saldo": hechos[-1]["saldo"],
            "ciclos_a_cero": len(plan) - len(hechos) if hechos[-1]["saldo"] < 0 else 0, "plan": plan}


GENERICAS = {"compra", "tarj", "tarjeta", "pago", "recibo", "www", "com", "cargo", "adeudo", "bizum", "transf"}


def clave_cargo(g):
    """El sitio de un cargo sin lo que cambia de un mes a otro: «NETFLIX.COM 866», «Netflix.com» e «IBERDROLA CLIENTES»
    son netflix e iberdrola. Una palabra basta: el importe parecido y el intervalo separan lo que no es lo mismo."""
    return next((w for w in re.findall(r"[a-z]{3,}", sin_tildes(g["comercio"] or g["nota"])) if w not in GENERICAS), "")


# Cada cuántos días se repite un cargo, y cuánto se le deja llegar tarde antes de darlo por dado de baja.
PERIODOS = {"semana": (5, 9, 3), "mes": (26, 35, 7), "año": (350, 380, 20)}


def recurrentes(gastos, hoy, marcas=None):
    """Lo que se repite: el mismo sitio (clave_cargo), un importe parecido (±10 %) y cada semana, mes o año. Lo de la
    categoría Suscripciones (o lo que el usuario confirmó) vale con un cobro. El súper y comer fuera no cuentan salvo
    confirmados: comprar cada semana en Mercadona no es una suscripción. Con el próximo cargo previsto."""
    marcas = marcas or {}
    grupos = {}
    for g in sorted(gastos, key=lambda g: g["dia"]):
        if not g["viaje"] and g["importe"] > 0 and (k := clave_cargo(g)) and (g["cat"] not in ("super", "fuera") or marcas.get(k) == "si"):
            grupos.setdefault(k, []).append(g)
    out = []
    for k, gs in grupos.items():
        u = gs[-1]
        cadena = [u]   # los cobros anteriores por casi lo mismo, del más reciente hacia atrás
        for p in reversed(gs[:-1]):
            if abs(p["importe"] - u["importe"]) <= max(.5, u["importe"] * .10):
                cadena.append(p)
                if len(cadena) == 6:
                    break
        cadena.reverse()
        difs = [x for a, b in zip(cadena, cadena[1:]) if (x := (date.fromisoformat(b["dia"]) - date.fromisoformat(a["dia"])).days) > 0]
        cada = None
        if difs:
            med = sorted(difs)[len(difs) // 2]
            cada = next((c for c, (lo, hi, _) in PERIODOS.items() if lo <= med <= hi and lo <= difs[-1] <= hi), None)
            if cada == "semana" and len(difs) < 2:   # dos cafés a una semana no son nada: hacen falta tres
                cada = None
        if not cada and (u["cat"] == "suscripciones" or marcas.get(k) == "si"):
            cada = "mes"
        if not cada:
            continue
        ud = date.fromisoformat(u["dia"])
        prox = (ud + timedelta(days=7) if cada == "semana" else dia_de(*mes_mas(ud.year, ud.month, 1), ud.day) if cada == "mes"
                else dia_de(ud.year + 1, ud.month, ud.day))
        if prox < hoy - timedelta(days=PERIODOS[cada][2]):   # tocaba y no ha llegado: dada de baja
            continue
        al_mes = round(u["importe"] * {"semana": 52 / 12, "mes": 1, "año": 1 / 12}[cada], 2)
        out.append({"clave": k, "n": u["comercio"] or u["nota"] or "sin nombre", "importe": u["importe"], "cada": cada,
                    "cat": u["cat"], "ultimo": u["dia"], "proximo": prox.isoformat(), "veces": len(cadena),
                    "al_mes": al_mes, "al_año": round(al_mes * 12, 2), "estado": marcas.get(k, "")})
    return sorted(out, key=lambda s: s["proximo"])


def suscripciones(gastos, hoy, marcas=None):
    """Los recurrentes que cuentan (los ignorados, fuera): los usan los insights, el bot y la web de siempre."""
    return [r for r in recurrentes(gastos, hoy, marcas) if r["estado"] != "no"]


# ---------- reglas de categoría ----------
# «Si el concepto contiene "mercadona" → Súper». Las propone el servidor al ver un patrón (o al corregir la categoría de
# un gasto), las acepta el usuario y se aplican solas a lo que entra por /api/gasto. Concepto = comercio + nota, sin tildes,
# en minúsculas y por palabras enteras: «bar» no casa con «barbería».
NADA = GENERICAS | {"con", "del", "las", "los", "para", "por", "una", "uno", "unos", "sin", "que", "the", "and", "mas", "visa",
                    "sl", "sa", "slu", "s.l", "online", "app", "store", "shop", "tienda", "pedido", "ajuste", "restar"}


def norma(s):
    return " ".join(re.findall(r"[a-z0-9&]+", sin_tildes(s)))


def concepto(g):
    return norma(f"{g.get('comercio') or ''} {g.get('nota') or ''}")


def encaja(txt, g):
    return bool(txt) and f" {txt} " in f" {concepto(g)} "


def regla_de(reglas, g):
    """La primera regla (en su orden: la prioridad) que casa con el gasto, o None."""
    return next((r for r in reglas if encaja(r["txt"], g)), None)


def patron(g):
    """La palabra que distingue un gasto: la primera con sentido del comercio (o, sin él, de la nota)."""
    return next((w for w in norma(g.get("comercio") or g.get("nota")).split()
                 if len(w) >= 3 and re.search(r"[a-z]", w) and w not in NADA), "")


def por_defecto(cats):
    ids = [c["id"] for c in cats]
    return "otros" if "otros" in ids else ids[-1]


def propuesta(estado, txt, cat, cambia=""):
    enc = [g for g in estado["gastos"] if encaja(txt, g)]
    cambian = [g for g in enc if g["cat"] != cat]
    return {"txt": txt, "cat": cat, "encajan": len(enc), "cambiarian": len(cambian), "cambia": cambia,
            "ejemplos": list(dict.fromkeys(g["comercio"] or g["nota"] for g in (cambian or enc)))[:3]}


def propuestas(estado):
    """Patrones claros que aún no son regla: la misma palabra, casi siempre en la misma categoría (no la de por
    defecto), al menos dos veces, y que la adivinanza de PISTAS no acierta ya sola. De más a menos gastos."""
    grupos = {}
    for g in estado["gastos"]:
        if p := patron(g):
            grupos.setdefault(p, []).append(g)
    defecto, cats = por_defecto(estado["cats"]), estado["cats"]
    hechas, no = {r["txt"] for r in estado["reglas"]}, set(estado["rechazadas"])
    out = []
    for p, gs in grupos.items():
        if p in hechas or p in no or any(regla_de(estado["reglas"], g) for g in gs):
            continue
        cuenta = {}
        for g in gs:
            if g["cat"] != defecto:
                cuenta[g["cat"]] = cuenta.get(g["cat"], 0) + 1
        orden = sorted(cuenta.items(), key=lambda kv: -kv[1])
        if not orden or orden[0][1] < 2 or (len(orden) > 1 and orden[1][1] * 2 > orden[0][1]):
            continue
        cat = orden[0][0]
        x = propuesta(estado, p, cat)
        if not x["cambiarian"] and all(adivina(concepto(g), cats) == cat for g in gs):
            continue   # ya sale sola: la regla no aportaría nada
        out.append(x)
    return sorted(out, key=lambda x: (-x["encajan"], x["txt"]))[:8]


def propuesta_de(estado, g):
    """Tras corregir (o elegir a mano) la categoría de un gasto: ¿hacer regla de su palabra? None si no hay nada
    que aprender (ya sale sola, ya hay regla igual o el usuario dijo que no a esa palabra)."""
    p = patron(g)
    if not p or p in estado["rechazadas"]:
        return None
    r = regla_de(estado["reglas"], g)
    if r and r["cat"] == g["cat"]:
        return None
    if not r and adivina(concepto(g), estado["cats"]) == g["cat"]:
        return None
    return propuesta(estado, p, g["cat"], r["id"] if r and r["txt"] == p else "")


def aplica_regla(estado, r):
    """Pasa a la categoría de la regla los gastos que casan con ella. Devuelve cuántos cambió."""
    n = 0
    for g in estado["gastos"]:
        if encaja(r["txt"], g) and g["cat"] != r["cat"]:
            g["cat"] = r["cat"]
            n += 1
    return n


def resumen(estado, ref=None, hoy=None):
    """Todo lo del ciclo que contiene ref: cifras, categorías, series para gráficas e insights."""
    hoy = hoy or date.today()
    ref = ref or hoy
    todo_ = estado
    # los viajes van aparte, con su hucha; lo que te devuelven entra como gasto en negativo en su categoría:
    # así la cena de 60 € que te pagan a medias queda en 30 en todas las cuentas (totales, ritmo, ciclos pasados)
    devuelto = [{**i, "importe": -i["importe"], "comercio": "", "viaje": "", "lineas": [], "reparto": "medias", "orig": 0, "moneda": ""}
                for i in estado["ingresos"] if i["tipo"] == "devuelve"]
    estado = {**estado, "gastos": [g for g in estado["gastos"] if not g["viaje"]] + devuelto}
    cobro, ingreso = estado["ajustes"]["dia_cobro"], estado["ajustes"]["ingreso"]
    ini, fin = ciclo(ref, cobro)
    dias = (fin - ini).days + 1
    hechos = 0 if hoy < ini else min(dias, (hoy - ini).days + 1)   # días ya vividos del ciclo
    del_ciclo = entre(estado, ini, fin)
    pini, pfin = ciclo(ini - timedelta(days=1), cobro)
    previo = entre(estado, pini, pfin)
    # la hucha de viajes es un fijo del ciclo: cuenta en el total desde el día de cobro
    aparte, aparte_previo = fijos_en(todo_, ini), fijos_en(todo_, pini)
    hucha_ciclo, inv_presu = aparte_en(todo_, ini), todo_["ajustes"]["inversion"]
    serie_previa = [round(x + aparte_previo, 2) for x in acumulado(previo, pini, (pfin - pini).days + 1)]
    sug = sugeridos(estado, hoy)
    frac = hechos / dias

    cats = []
    for c in estado["cats"]:
        g = suma(del_ciclo, c["id"])
        proy = g if (c["id"] in FIJOS or not frac or hechos == dias) else g / frac
        estado_c = ("pasado" if c["presu"] and g > c["presu"] else
                    "ojo" if c["presu"] and hechos >= 3 and proy > c["presu"] * 1.05 else "ok")
        cats.append({**c, "gastado": g, "proyeccion": round(proy, 2), "estado": estado_c,
                     "devuelto": -suma([x for x in del_ciclo if x["importe"] < 0], c["id"]),
                     "anterior": suma(previo, c["id"]), "sugerido": sug[c["id"]]["importe"],
                     "por": sug[c["id"]]["por"]})

    historico, f = [], fin
    for _ in range(6):
        i, ff = ciclo(f, cobro)
        historico.append({"inicio": i.isoformat(), "fin": ff.isoformat(), "total": round(suma(entre(estado, i, ff)) + fijos_en(todo_, i), 2)})
        f = i - timedelta(days=1)
    historico.reverse()

    ayer = (hoy - timedelta(days=1)).isoformat()
    r = {
        "inicio": ini.isoformat(), "fin": fin.isoformat(), "dias": dias, "hechos": hechos,
        "actual": ini <= hoy <= fin,
        "total": round(suma(del_ciclo) + aparte, 2),
        "aparte": hucha_ciclo,   # la hucha de viajes de este ciclo (la inversión va en «inversion»)
        "fijos": aparte,
        "inversion": {"presu": round(inv_presu + multas_en(ini, fin)[0], 2) if inv_presu else 0, "base": inv_presu,
                      "multas": multas_en(ini, fin)[0], "n_multas": len(multas_en(ini, fin)[1]),
                      "aportado": aportado(ini, fin), "cuenta": invertido_en(todo_, ini),
                      "desde": todo_["ajustes"]["inversion_desde"]} if inv_presu or INVERSIONES.exists() else None,
        "ingresos": [i for i in todo_["ingresos"] if ini.isoformat() <= i["dia"] <= fin.isoformat()],
        "extra": suma([i for i in todo_["ingresos"] if i["tipo"] == "extra" and ini.isoformat() <= i["dia"] <= fin.isoformat()]),
        "presu": round(sum(c["presu"] for c in estado["cats"]) + aparte, 2) if any(c["presu"] for c in estado["cats"]) else 0,
        "ingreso": ingreso, "dia_cobro": cobro,
        "proyeccion": round(sum(c["proyeccion"] for c in cats) + aparte, 2),
        "anterior_a_esta_altura": serie_previa[min(hechos, len(serie_previa)) - 1] if hechos and serie_previa else 0,
        "cats": cats,
        "ayer": suma([g for g in estado["gastos"] if g["dia"] == ayer]),
        "n": len([g for g in del_ciclo if g["importe"] > 0]),
        "serie": [round(x + aparte, 2) for x in acumulado(del_ciclo, ini, dias)][:hechos],
        "serie_previa": serie_previa,
        "historico": historico,
        "sugerido_total": sum(s["importe"] for s in sug.values()),
        "hucha": hucha(todo_, hoy),
        "recurrentes": recurrentes(todo_["gastos"], hoy, todo_.get("recurrentes")),
        "suscripciones": suscripciones(todo_["gastos"], hoy, todo_.get("recurrentes")),
        "cuentas": cuentas_de(todo_),
        "pareja": PAREJA,
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
        # la proyección ya lleva lo apartado para viajes (eso no es ahorro); los ingresos extra suman a lo que cobras
        ahorro = r["ingreso"] + r["extra"] - r["proyeccion"]
        pct = round(ahorro * 100 / (r["ingreso"] + r["extra"]))
        apartes = ([f"{eur(r['aparte'])} apartados para viajes"] if r["aparte"] else []) + \
                  ([f"{eur(r['inversion']['cuenta'])} invertidos"] if r["inversion"] and r["inversion"]["cuenta"] else [])
        y_viajes = (", aparte de " if r["inversion"] and r["inversion"]["cuenta"] else ", con ") + " y ".join(apartes) if apartes else ""
        out.append(("ok" if pct >= 20 else "ojo" if pct >= 0 else "mal",
                    f"A este ritmo cerrarás el ciclo en {eur(r['proyeccion'])}"
                    + (f" y ahorrarás {eur(ahorro)} ({pct} %){y_viajes}." if ahorro >= 0 else f": {eur(-ahorro)} más de lo que cobras{y_viajes}.")))
    if r["actual"]:
        for s in r["suscripciones"]:
            d = (date.fromisoformat(s["proximo"]) - hoy).days
            if 0 <= d <= 2:
                out.append(("ojo", f"{('Hoy', 'Mañana', 'Pasado mañana')[d]} se cobra {s['n']}: {eur(s['importe'])}."))
        if r["extra"]:
            out.append(("ok", f"Te han entrado {eur(r['extra'])} " + ("aparte del sueldo" if r["ingreso"] else "este mes")
                              + f" ({', '.join((i['nota'] or i['comercio'] or 'sin nota') for i in r['ingresos'] if i['tipo'] == 'extra')[:80]})."))
        if r["suscripciones"]:
            al_mes = sum(s["al_mes"] for s in r["suscripciones"])
            out.append(("info", f"Gastos que se repiten: {len(r['suscripciones'])}, {eur(al_mes)} al mes ({eur(al_mes * 12)} al año)."))
        if (inv := r["inversion"]) and inv["presu"] and inv["aportado"] is not None:
            falta = round(inv["presu"] - inv["aportado"], 2)
            de_multas = f" ({eur(inv['multas'])} son multas por hábitos)" if inv["multas"] else ""
            out.append(("ok", f"Ya has invertido {eur(inv['aportado'])} este ciclo, de {eur(inv['presu'])} previstos{de_multas}.") if falta <= 0 else
                       ("ojo" if quedan <= 5 else "info",
                        f"Te quedan {eur(falta)} por invertir este ciclo (llevas {eur(inv['aportado'])} de {eur(inv['presu'])}{de_multas})."))
        if r["hucha"] and r["hucha"]["saldo"] < 0:
            out.append(("info", f"La hucha de viajes está en {eur(r['hucha']['saldo'])}: "
                                f"vuelve a cero en {r['hucha']['ciclos_a_cero']} ciclo{'s' if r['hucha']['ciclos_a_cero'] > 1 else ''}."))
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
        # una pestaña abierta desde antes de las reglas no las conoce: lo que no trae se conserva
        if any(k not in estado for k in ("reglas", "rechazadas", "recurrentes")):
            antes = lee()
            estado = {**{k: antes[k] for k in ("reglas", "rechazadas", "recurrentes")}, **estado}
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
        elegida = de_nombre(a.get("cat"), estado["cats"])
        src = str(a.get("src") or "atajo")
        # una regla aceptada gana a lo que adivina el servidor y a la categoría que propone Claude (bot, ticket, banco,
        # Apple Pay); lo que una persona eligió a mano (web, Tom, Siri, el atajo) se respeta
        regla = regla_de(estado["reglas"], {"comercio": comercio, "nota": nota})
        mano = bool(elegida) and src in ("web", "siri", "atajo")
        cat = regla["cat"] if regla and not mano else elegida or adivina(f"{comercio} {nota} {a.get('cat') or ''}", estado["cats"])
        regla = regla if regla and cat == regla["cat"] else None
        dia = day(a.get("dia")) or date.today().isoformat()
        g = {"id": str(a.get("id") or "")[:40] or f"{dia}-{time.time_ns() % 10**9}", "dia": dia, "importe": imp,
             "cat": cat, "nota": nota, "comercio": comercio, "src": a.get("src") or "atajo", "lineas": a.get("lineas"),
             "reparto": a.get("reparto") or "medias"}
        g["viaje"] = de_viaje(a["viaje"], estado["viajes"]) if a.get("viaje") else que_viaje(g, estado["viajes"])
        v = next((v for v in estado["viajes"] if v["id"] == g["viaje"]), None)
        mon = m if (m := str(a.get("moneda") or "").upper()) in MONEDAS else moneda_de(a.get("importe"))
        if v and v["moneda"] != "EUR" and v["cambio"] and mon in ("", v["moneda"]) and g["src"] != "banco":
            # en un viaje, lo que no dice moneda va en la del viaje: Apple Pay en Londres manda libras
            g["orig"], g["moneda"], g["importe"] = imp, v["moneda"], round(imp * v["cambio"], 2)
        antes = resumen(estado, date.fromisoformat(dia))
        e = estimado(estado, g) if g["src"] == "banco" else None
        if e:   # el cargo real de algo apuntado en otra moneda: corrige la estimación en vez de duplicarlo
            e["importe"], e["src"] = imp, "banco"
            g = e
        else:   # mismo id dos veces = el atajo se disparó repetido: se reemplaza, no se duplica
            estado["gastos"] = [x for x in estado["gastos"] if x["id"] != g["id"]] + [g]
        estado = escribe(estado)
    g = next(x for x in estado["gastos"] if x["id"] == g["id"])
    r = resumen(estado, date.fromisoformat(g["dia"]))
    c = next(x for x in r["cats"] if x["id"] == g["cat"])
    donde = ((f" · {g['comercio']}" if g["comercio"] else (f" · {g['nota']}" if g["nota"] else ""))
             + (f" · {en_moneda(g['orig'], g['moneda'])}" if g["orig"] else "") + (" · ya con el cargo real del banco" if e else ""))
    v = next((v for v in estado["viajes"] if v["id"] == g["viaje"]), None)
    if v:   # va aparte: el texto habla del viaje (y de mi parte, si es compartido), no del ciclo
        cu = cuentas(v, estado, de_la_pareja() if v["con"] else None)
        texto = (f"{eur(g['importe'])} en {c['n']}{donde} · viaje {v['n']}\n{v['n']}: "
                 + (f"{eur(cu['total'])} · tu parte {eur(cu['parte'])}" if v["con"] else eur(cu["total"]))
                 + (f" de {eur(v['presu'])}" if v["presu"] else ""))
        alertas = aviso_viaje(v, cu["parte"] - mi_parte(g, True, v["con"]), cu["parte"])
    else:
        texto = f"{eur(g['importe'])} en {c['n']}{donde}\nEste ciclo: {eur(r['total'])}"
        if c["presu"]:
            texto += f" · {c['n']}: {eur(c['gastado'])} de {eur(c['presu'])}"
        alertas = avisos(antes, r, g)
    if alertas:
        texto += "\n" + "\n".join(alertas)
        # lo que entra por el bot ya contesta en Telegram con este texto: no avisar dos veces
        if g["src"] not in ("bot", "ticket", "banco", "correo"):
            telegram("\n".join(alertas))
    # elegida a mano y distinta de lo que saldría solo: se ofrece hacer regla (Tom y la web la enseñan)
    # (una nota larga, «tomate, carne y queso», no tiene una palabra que valga como regla)
    sugiere = propuesta_de(estado, g) if mano and (comercio or 0 < len(norma(nota).split()) <= 2) else None
    return {"texto": texto, "gasto": g, "avisos": alertas, "regla": regla["txt"] if regla else "", "propuesta": sugiere}


@app.post("/api/gasto/borra")
def borra_gasto(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Quita un gasto por su id (el botón «Quitar» de lo que el bot apuntó solo, p. ej. desde el correo)."""
    exige(gastos_sesion, authorization)
    gid = str(a.get("id") or "")
    with cerrojo:
        estado = lee()
        g = next((x for x in estado["gastos"] if x["id"] == gid), None)
        if not g:
            raise HTTPException(404, "ese gasto ya no está")
        estado["gastos"] = [x for x in estado["gastos"] if x["id"] != gid]
        escribe(estado)
    return {"ok": True, "gasto": g, "texto": f"Quitado: {eur(g['importe'])}" + (f" · {g['comercio'] or g['nota']}" if g["comercio"] or g["nota"] else "")}


# ---------- reglas y recurrentes ----------
# La web y el bot usan estas rutas; Tom manda lo mismo como operaciones de su cola sobre /api/estado (sin red).
def con_cuenta(estado):
    return [{**r, "encajan": sum(1 for g in estado["gastos"] if encaja(r["txt"], g))} for r in estado["reglas"]]


@app.get("/api/reglas")
def get_reglas(id: str = "", gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Las reglas (en orden de prioridad, con cuántos gastos casan) y las propuestas. Con `id`, la de ese gasto en `para`."""
    exige(gastos_sesion, authorization)
    e = lee()
    g = next((x for x in e["gastos"] if x["id"] == id), None) if id else None
    return {"reglas": con_cuenta(e), "propuestas": propuestas(e), "para": propuesta_de(e, g) if g else None}


@app.post("/api/regla")
def pon_regla(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Crea o cambia una regla {txt, cat, id?, aplicar?}. Con `aplicar`, también los gastos de antes que casan."""
    exige(gastos_sesion, authorization)
    txt = norma(a.get("txt"))[:40]
    with cerrojo:
        e = lee()
        cat = de_nombre(a.get("cat"), e["cats"])
        if not txt or not cat:
            raise HTTPException(400, "Una regla necesita un texto que buscar y una categoría que exista")
        rid = str(a.get("id") or "")[:24] or next((r["id"] for r in e["reglas"] if r["txt"] == txt), "") or f"r{time.time_ns() % 10**9}"
        r = {"id": rid, "txt": txt, "cat": cat}
        i = next((i for i, x in enumerate(e["reglas"]) if x["id"] == rid), None)
        otras = [x for x in e["reglas"] if x["id"] != rid and x["txt"] != txt]
        e["reglas"] = otras[:i] + [r] + otras[i:] if i is not None else otras + [r]
        n = aplica_regla(e, r) if a.get("aplicar") else 0
        e = escribe(e)
    return {"regla": r, "aplicados": n, "reglas": con_cuenta(e)}


@app.post("/api/regla/borra")
def borra_regla(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    exige(gastos_sesion, authorization)
    with cerrojo:
        e = lee()
        e["reglas"] = [r for r in e["reglas"] if r["id"] != a.get("id")]
        e = escribe(e)
    return {"reglas": con_cuenta(e)}


@app.post("/api/regla/aplica")
def aplica_una(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """«Aplicar a los gastos anteriores»: los que casan con la regla pasan a su categoría."""
    exige(gastos_sesion, authorization)
    with cerrojo:
        e = lee()
        r = next((r for r in e["reglas"] if r["id"] == a.get("id")), None)
        if not r:
            raise HTTPException(404, "Esa regla ya no existe: la han borrado desde otro sitio")
        n = aplica_regla(e, r)
        escribe(e)
    return {"aplicados": n}


@app.post("/api/regla/rechaza")
def rechaza_regla(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """«No, gracias»: esa palabra no se vuelve a proponer."""
    exige(gastos_sesion, authorization)
    with cerrojo:
        e = lee()
        e["rechazadas"].append(norma(a.get("txt")))
        e = escribe(e)
    return {"propuestas": propuestas(e)}


@app.post("/api/reglas/orden")
def ordena_reglas(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """La prioridad: la primera que casa gana. Las que no vengan en `ids` quedan detrás, como estaban."""
    exige(gastos_sesion, authorization)
    ids = [str(x) for x in lst(a.get("ids"))]
    with cerrojo:
        e = lee()
        e["reglas"] = ([r for i in ids for r in e["reglas"] if r["id"] == i] + [r for r in e["reglas"] if r["id"] not in ids])
        e = escribe(e)
    return {"reglas": con_cuenta(e)}


@app.get("/api/recurrentes")
def get_recurrentes(gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Lo que se repite (también lo ignorado, para poder deshacerlo) y cuánto suma al mes y al año lo que cuenta."""
    exige(gastos_sesion, authorization)
    e = lee()
    l = recurrentes(e["gastos"], date.today(), e["recurrentes"])
    al_mes = round(sum(r["al_mes"] for r in l if r["estado"] != "no"), 2)
    return {"recurrentes": l, "al_mes": al_mes, "al_año": round(al_mes * 12, 2)}


@app.post("/api/recurrente")
def marca_recurrente(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """{clave, estado: si (confirmado) | no (ignorado) | "" (como lo detecte el servidor)}."""
    exige(gastos_sesion, authorization)
    clave = str(a.get("clave") or "").strip()[:60]
    if not clave:
        raise HTTPException(400, "Falta la clave del gasto recurrente")
    with cerrojo:
        e = lee()
        if a.get("estado") in ("si", "no"):
            e["recurrentes"][clave] = a["estado"]
        else:
            e["recurrentes"].pop(clave, None)
        escribe(e)
    return {"clave": clave, "estado": a.get("estado") if a.get("estado") in ("si", "no") else ""}


@app.post("/api/ingreso")
def apunta_ingreso(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Un ingreso de una sola llamada, como /api/gasto: para la web, el bot y las capturas del banco."""
    exige(gastos_sesion, authorization)
    imp = importe(a.get("importe"))
    if not imp:
        raise HTTPException(400, f"«{a.get('importe')}» no es un importe")
    with cerrojo:
        estado = lee()
        comercio, nota = str(a.get("comercio") or "").strip(), str(a.get("nota") or "").strip()
        tipo = "devuelve" if a.get("tipo") == "devuelve" else "extra"
        cat = (de_nombre(a.get("cat"), estado["cats"]) or adivina(f"{comercio} {nota} {a.get('cat') or ''}", estado["cats"])
               if tipo == "devuelve" else "")
        dia = day(a.get("dia")) or date.today().isoformat()
        x = {"id": str(a.get("id") or "")[:40] or f"i{dia}-{time.time_ns() % 10**9}", "dia": dia, "importe": imp, "tipo": tipo,
             "cat": cat, "nota": nota, "comercio": comercio, "src": a.get("src") or "web"}
        estado["ingresos"] = [y for y in estado["ingresos"] if y["id"] != x["id"]] + [x]
        estado = escribe(estado)
    x = next(y for y in estado["ingresos"] if y["id"] == x["id"])
    r = resumen(estado, date.fromisoformat(x["dia"]))
    donde = f" · {x['nota'] or x['comercio']}" if x["nota"] or x["comercio"] else ""
    if tipo == "devuelve":
        c = next(c for c in r["cats"] if c["id"] == x["cat"])
        texto = (f"+{eur(imp)} · te devuelven de {c['n']}{donde}\n{c['n']} este ciclo: {eur(c['gastado'])}"
                 + (f" de {eur(c['presu'])}" if c["presu"] else ""))
    else:
        texto = f"+{eur(imp)} · ingreso extra{donde}\nExtras este ciclo: {eur(r['extra'])}"
    return {"texto": texto, "ingreso": x}


@app.post("/api/viaje")
def nuevo_viaje(a: dict = Body(...), gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Crea un viaje y se lleva los gastos que ya eran suyos (reservas, los que lo nombran, los de esos días)."""
    exige(gastos_sesion, authorization)
    desde, hasta = day(a.get("desde")), day(a.get("hasta")) or day(a.get("desde"))
    if not str(a.get("n") or "").strip() or not desde:
        raise HTTPException(400, "Un viaje necesita nombre y fechas")
    mon = m if (m := str(a.get("moneda") or "EUR").upper()) in MONEDAS else "EUR"
    cam = tasa(a.get("cambio")) or (cambio_de(mon) if mon != "EUR" else 0)   # fuera del cerrojo: va a internet
    with cerrojo:
        estado = lee()
        v = {"id": f"v{time.time_ns() % 10**9}", "n": a["n"], "desde": desde, "hasta": hasta, "presu": a.get("presu"),
             "moneda": mon, "cambio": cam, "con": bool(a.get("con"))}
        estado["viajes"].append(v)
        estado = clean(estado)
        v = estado["viajes"][-1]
        movidos = [g for g in estado["gastos"] if not g["viaje"] and que_viaje(g, [v])]
        for g in movidos:
            g["viaje"] = v["id"]
        escribe(estado)
    return {"viaje": v, "movidos": movidos}


@app.get("/api/cambio")
def get_cambio(moneda: str = "GBP", gastos_sesion: str = Cookie(None), authorization: str = Header(None)):
    """Euros por unidad de hoy, para rellenar el cambio de un viaje."""
    exige(gastos_sesion, authorization)
    m = moneda.upper()
    if m not in MONEDAS:
        raise HTTPException(400, "Moneda desconocida")
    return {"moneda": m, "cambio": 1 if m == "EUR" else cambio_de(m)}


# Otra persona con su propia instancia pone su nombre en la
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
# La apariencia elegida en todo (Ajustes → Apariencia): calma.js la pide para que todas las apps se vean igual.
# Solo colores, letra y esquinas; nada privado. La disposición de pantallas es cosa de todo.
@app.get("/api/apariencia")
def apariencia_comun():
    import json as _json
    from pathlib import Path as _Path
    try:
        return {"apariencia": _json.loads(_Path("/home/pi/todo/ajustes.json").read_text("utf-8")).get("apariencia") or {}}
    except Exception:
        return {"apariencia": {}}


app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
