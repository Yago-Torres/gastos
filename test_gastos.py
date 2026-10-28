"""Comprobaciones de gastos. Sin frameworks: uv run python test_gastos.py"""
import os
import tempfile
from datetime import date

os.environ["GASTOS_DB"] = os.path.join(tempfile.mkdtemp(), "data.json")
os.environ["GASTOS_COMIDA"] = "/no/existe"   # que el súper salga del % y no de comida
os.environ.pop("TELEGRAM_TOKEN", None)        # las pruebas no mandan nada a Telegram
import main as m  # noqa: E402

# importes como los manda Atajos (formato del iPhone), Apple Pay y la web
assert m.importe("12,50 €") == 12.5
assert m.importe("1.234,56") == 1234.56
assert m.importe("1,234.56") == 1234.56
assert m.importe("12.5") == 12.5
assert m.importe(-7) == 7
assert m.importe("€ 3") == 3
assert m.importe("") is None and m.importe("abc") is None and m.importe(0) is None and m.importe(True) is None

# categoría por comercio o nota
cats = m.clean(m.EMPTY)["cats"]
assert m.adivina("MERCADONA S.A.", cats) == "super"
assert m.adivina("Uber Eats pedido", cats) == "fuera"
assert m.adivina("UBER *TRIP", cats) == "transporte"
assert m.adivina("cena con amigos", cats) == "fuera"
assert m.adivina("Media Markt", cats) == "otros"          # "dia" no casa dentro de "media"
assert m.adivina("ESTANCO N 3", cats) == "otros"                # sin categoría de tabaco
assert m.adivina("ESTANCO N 3", cats + [{"id": "tabaco", "n": "Tabaco", "presu": 0}]) == "tabaco"
assert m.de_nombre("Comer fuera", cats) == "fuera" and m.de_nombre("súper", cats) == "super"

# ciclos de cobro: del 28 al 27, y el día que no existe en el mes se recorta
d = date
assert m.ciclo(d(2026, 10, 25), 28) == (d(2026, 9, 28), d(2026, 10, 27))
assert m.ciclo(d(2026, 10, 28), 28) == (d(2026, 10, 28), d(2026, 11, 27))
assert m.ciclo(d(2026, 1, 5), 28) == (d(2025, 12, 28), d(2026, 1, 27))
assert m.ciclo(d(2026, 2, 28), 31) == (d(2026, 2, 28), d(2026, 3, 30))
assert m.ciclo(d(2026, 3, 1), 1) == (d(2026, 3, 1), d(2026, 3, 31))

# clean: idempotente, tira lo roto, no duplica ids y trae ajustes por defecto
sucio = {"cats": cats, "gastos": [
    {"id": "a", "dia": "2026-10-25", "importe": "3,20", "cat": "super"},
    {"id": "a", "dia": "2026-10-25", "importe": 9, "cat": "super"},     # id repetido
    {"id": "b", "dia": "2026-13-40", "importe": 5},                    # fecha imposible
    {"id": "c", "dia": "2026-10-24", "importe": 5, "cat": "inventada"},  # categoría que no existe
], "ajustes": {"ingreso": "x", "dia_cobro": 45}}
limpio = m.clean(sucio)
assert [g["id"] for g in limpio["gastos"]] == ["c", "a"], limpio
assert limpio["gastos"][0]["cat"] == "otros" and limpio["gastos"][1]["importe"] == 3.2
assert limpio["ajustes"] == {"ingreso": 1600, "dia_cobro": 31}
assert m.clean(limpio) == limpio

# cuánto debería gastar: % de 1600 redondeado a 5 €, y el ahorro es lo que sobra
sug = m.sugeridos(limpio, d(2026, 10, 25))
assert sug["casa"]["importe"] == 480 and sug["fuera"]["importe"] == 130 and sug["super"]["importe"] == 175
assert 1600 - sum(s["importe"] for s in sug.values()) == 320    # el 20 % de ahorro

# la llamada del atajo: categoría por nombre, por pista, texto de la notificación y sin duplicar
m.PASS, m.SECRET = "x", b"y"
r = m.apunta({"importe": "12,50 €", "cat": "Comer fuera", "id": "t1"}, None, "Bearer x")
assert r["gasto"]["cat"] == "fuera" and r["texto"].startswith("12,50 € en Comer fuera"), r
m.apunta({"importe": "12,50 €", "cat": "Comer fuera", "id": "t1"}, None, "Bearer x")
assert len(m.lee()["gastos"]) == 1
r = m.apunta({"importe": 40, "comercio": "LIDL SUPERMERCADOS"}, None, "Bearer x")
assert r["gasto"]["cat"] == "super"
assert m.resumen(m.lee())["total"] == 52.5
assert m.eur(1234.5) == "1.234,50 €"

# avisos: una vez al cruzar el 80 % y otra al pasarse; por debajo, nada
e = m.lee()
for c in e["cats"]:
    c["presu"] = {"fuera": 100, "super": 60}.get(c["id"], 0)      # total del ciclo: 160 €
m.escribe(e)
assert m.apunta({"importe": 60, "cat": "fuera"}, None, "Bearer x")["avisos"] == []      # 72,50 €
assert "80 %" not in str(m.apunta({"importe": 1, "cat": "fuera"}, None, "Bearer x")["avisos"])
a = m.apunta({"importe": 10, "cat": "fuera"}, None, "Bearer x")["avisos"]           # 83,50 €
assert len(a) == 1 and a[0].startswith("🟡"), a
assert m.apunta({"importe": 5, "cat": "fuera"}, None, "Bearer x")["avisos"] == []       # sigue en amarillo
a = m.apunta({"importe": 20, "cat": "fuera"}, None, "Bearer x")["avisos"]           # 108,50 € (total 148,50)
assert len(a) == 1 and a[0].startswith("🔴 Te has pasado en Comer fuera"), a
a = m.apunta({"importe": 15, "cat": "otros"}, None, "Bearer x")["avisos"]           # total 163,50 > 160
assert a == ["🔴 Te has pasado del presupuesto del ciclo: 163,50 € de 160,00 €."], a
res = m.resumen(m.lee())
assert next(c for c in res["cats"] if c["id"] == "fuera")["estado"] == "pasado"
assert res["insights"][0]["nivel"] == "mal" and len(res["historico"]) == 6
assert len(res["serie"]) == res["hechos"] and res["serie"][-1] == res["total"]

# ingreso variable (otra instancia): meses naturales y lo que debería gastar sale de su media, no de un %
from datetime import date as _d
viejos = m.AJUSTES
m.AJUSTES = {"ingreso": 0.0, "dia_cobro": 1}
e = m.clean({"gastos": [{"id": "a", "dia": "2026-09-10", "importe": 30, "cat": "fuera"},
                        {"id": "b", "dia": "2026-08-10", "importe": 50, "cat": "fuera"}]})
assert e["ajustes"] == {"ingreso": 0.0, "dia_cobro": 1}, e["ajustes"]
s = m.sugeridos(e, _d(2026, 10, 15))
assert s["fuera"] == {"importe": 40, "por": "lo que gastas de media al mes"} and s["super"]["importe"] == 0, s
r = m.resumen(e, hoy=_d(2026, 10, 15))
assert (r["inicio"], r["fin"]) == ("2026-10-01", "2026-10-31"), (r["inicio"], r["fin"])
assert any("lo que gastas de media, 40,00 €" in i["texto"] for i in r["insights"]), r["insights"]
assert not any("ahorr" in i["texto"] for i in r["insights"]), r["insights"]
m.AJUSTES = viejos

# una instancia con nombre (una segunda) lo pone en la página; la principal se queda igual
h = '<title>Gastos</title><meta name="apple-mobile-web-app-title" content="Gastos"><h1>Gastos</h1>'
assert m.con_nombre(h, "") == h
assert m.con_nombre(h, "Ana") == ('<title>Gastos · Ana</title><meta name="apple-mobile-web-app-title" '
                                     'content="Gastos Ana"><h1>Gastos · Ana</h1>')
print("ok")
