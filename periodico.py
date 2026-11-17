#!/usr/bin/env python3
"""
Periódico para Kindle.

Arma una portada estilo diario con noticias (RSS) y el clima de la semana,
la guarda como PNG en escala de grises con la resolución exacta del Kindle
y la deja disponible en la red local para que el Kindle la descargue.

Uso:
    python periodico.py              # genera, sirve en la red y se actualiza solo
    python periodico.py --una-vez    # genera portada.png y termina
    python periodico.py --probar     # revisa qué fuentes de noticias responden
    python periodico.py --ejemplo    # genera con noticias de ejemplo (sin internet)
"""

import base64
import datetime as dt
import html
import http.server
import json
import re
import socket
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

CARPETA = Path(__file__).resolve().parent
SALIDA = CARPETA / "salida"
CONFIG = json.loads((CARPETA / "config.json").read_text(encoding="utf-8"))

MODELOS = {
    "kindle_4": (600, 800),
    "kindle_basico_2016": (600, 800),
    "paperwhite_7": (1072, 1448),
    "paperwhite_10": (1072, 1448),
    "oasis": (1264, 1680),
    "paperwhite_11": (1236, 1648),
}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_CORTOS = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

AGENTE = {"User-Agent": "Mozilla/5.0 (periodico-kindle)"}


# ---------------------------------------------------------------- descargas

def descargar(url, tiempo=15):
    req = urllib.request.Request(url, headers=AGENTE)
    with urllib.request.urlopen(req, timeout=tiempo) as r:
        return r.read()


def limpiar(texto, largo=None):
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = html.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    # Quita el texto automático de WordPress y similares
    texto = re.sub(r"\s*The post .*? appeared first on .*$", "", texto, flags=re.I)
    texto = re.sub(r"\s*La entrada .*? se publicó primero en .*$", "", texto, flags=re.I)
    texto = re.sub(r"\s*(Leer|Seguir leyendo|Continue reading|Read more)[^.]*\.?\s*$", "", texto, flags=re.I)
    texto = re.sub(r"\s*\[(…|\.\.\.|&hellip;)\]\s*", "… ", texto).strip()
    if largo and len(texto) > largo:
        texto = texto[:largo].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
    return texto


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def leer_rss(url):
    """Devuelve una lista de noticias {titulo, resumen, imagen, fuente}."""
    raiz = ET.fromstring(descargar(url))
    fuente = ""
    for el in raiz.iter():
        if _local(el.tag) == "title" and el.text:
            fuente = limpiar(el.text)
            break

    noticias = []
    for item in raiz.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        titulo, resumen, imagen = "", "", None
        for hijo in item:
            nombre = _local(hijo.tag)
            if nombre == "title":
                titulo = limpiar(hijo.text)
            elif nombre in ("description", "summary", "encoded", "content") and not resumen:
                crudo = hijo.text or ""
                resumen = limpiar(crudo)
                m = re.search(r'<img[^>]+src="([^"]+)"', crudo)
                if m and not imagen:
                    imagen = m.group(1)
            elif nombre in ("enclosure", "content", "thumbnail"):
                url_img = hijo.get("url")
                tipo = hijo.get("type", "image")
                if url_img and "image" in tipo and not imagen:
                    imagen = url_img
            elif nombre == "group":  # media:group
                for sub in hijo:
                    if sub.get("url") and not imagen:
                        imagen = sub.get("url")
        if titulo:
            noticias.append({"titulo": titulo, "resumen": resumen,
                             "imagen": imagen, "fuente": fuente})
    return noticias


def noticias_de(seccion, cantidad=1, con_imagen=False):
    """Prueba las fuentes en orden y usa la primera que responda."""
    for url in seccion["fuentes"]:
        try:
            lista = leer_rss(url)
        except Exception as e:
            print(f"  · {url} no respondió ({e.__class__.__name__})")
            continue
        if not lista:
            continue
        if con_imagen:
            lista.sort(key=lambda n: n["imagen"] is None)  # primero las que tienen foto
        return lista[:cantidad]
    return [{"titulo": "Sin noticias disponibles", "resumen":
             "Ninguna de las fuentes configuradas respondió.", "imagen": None, "fuente": ""}]


def imagen_en_linea(url):
    if not url:
        return None
    try:
        datos = descargar(url, 20)
    except Exception:
        return None
    tipo = "image/png" if datos[:4] == b"\x89PNG" else "image/jpeg"
    return f"data:{tipo};base64,{base64.b64encode(datos).decode()}"


# ------------------------------------------------------------------ clima

ICONOS = {  # códigos WMO de Open-Meteo
    0: "☀", 1: "☀", 2: "⛅", 3: "☁", 45: "≋", 48: "≋",
    51: "☂", 53: "☂", 55: "☂", 61: "☂", 63: "☂", 65: "☔",
    66: "☂", 67: "☔", 71: "❄", 73: "❄", 75: "❄", 77: "❄",
    80: "☂", 81: "☔", 82: "☔", 85: "❄", 86: "❄", 95: "⚡", 96: "⚡", 99: "⚡",
}


def clima():
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={CONFIG['latitud']}&longitude={CONFIG['longitud']}"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min"
           f"&timezone={CONFIG['zona_horaria']}&forecast_days=7")
    try:
        d = json.loads(descargar(url))["daily"]
    except Exception as e:
        print(f"  · clima no disponible ({e.__class__.__name__})")
        return []
    dias = []
    for fecha, cod, tmax, tmin in zip(d["time"], d["weather_code"],
                                      d["temperature_2m_max"], d["temperature_2m_min"]):
        f = dt.date.fromisoformat(fecha)
        dias.append({"dia": f"{DIAS_CORTOS[f.weekday()]} {f.day}",
                     "icono": ICONOS.get(cod, "·"),
                     "temp": f"{round(tmin)}° / {round(tmax)}°"})
    return dias


# ---------------------------------------------------------------- portada

def datos_reales():
    s = CONFIG["secciones"]
    print("Leyendo noticias…")
    principal = noticias_de(s["principal"], 1, con_imagen=True)[0]
    principal["imagen"] = imagen_en_linea(principal["imagen"])
    columnas = []
    for clave in ("columna1", "columna2", "columna3"):
        columnas.append({"seccion": s[clave]["nombre"], "noticias": noticias_de(s[clave], 5)})
    return {"principal": {**principal, "seccion": s["principal"]["nombre"]},
            "columnas": columnas, "clima": clima()}


def datos_ejemplo():
    hoy = dt.date.today()
    return {
        "principal": {
            "seccion": "Chile",
            "titulo": "Lluvias intensas obligan a suspender clases en tres comunas de Los Lagos",
            "resumen": "Las autoridades regionales informaron que el sistema frontal se mantendrá "
                       "hasta el jueves, con acumulados que podrían superar los 80 milímetros en "
                       "sectores cordilleranos. Se recomienda evitar traslados innecesarios.",
            "imagen": None, "fuente": "Ejemplo"},
        "columnas": [
            {"seccion": "Mundo", "noticias": [
                {"titulo": "Cumbre climática cierra con un acuerdo parcial sobre financiamiento",
                 "resumen": "Los países negociadores alcanzaron un texto común en la madrugada, aunque varios temas quedaron para la próxima ronda de conversaciones, prevista para el primer semestre del próximo año."},
                {"titulo": "Elecciones regionales marcan alta participación en Europa",
                 "resumen": "Las autoridades electorales destacaron la afluencia de votantes jóvenes y la rapidez del conteo en la mayoría de los distritos."},
                {"titulo": "Nueva ruta marítima acorta los envíos entre Asia y Sudamérica",
                 "resumen": "Las navieras estiman ahorros de hasta cinco días por trayecto gracias al nuevo corredor."}]},
            {"seccion": "Tecnología", "noticias": [
                {"titulo": "Las pantallas de tinta electrónica a color llegan a más lectores",
                 "resumen": "Los nuevos paneles mejoran el contraste y reducen el consumo, lo que abre la puerta a usos como paneles informativos y señalética en tiendas y estaciones."},
                {"titulo": "Crece el uso de lectores electrónicos como pantallas domésticas",
                 "resumen": "Aficionados reutilizan equipos antiguos para mostrar calendarios, clima y titulares con un consumo mínimo de batería."},
                {"titulo": "Chile amplía la cobertura de fibra óptica en el sur",
                 "resumen": "El proyecto suma localidades de Chiloé y la Región de Aysén durante el próximo año."}]},
            {"seccion": "Economía", "noticias": [
                {"titulo": "El cobre sube por tercer día consecutivo",
                 "resumen": "El metal rojo se apoya en mejores datos de demanda y en un dólar más débil a nivel global durante la jornada."},
                {"titulo": "Exportaciones de salmón muestran un alza en el trimestre",
                 "resumen": "La industria acuícola de Los Lagos lidera el crecimiento, impulsada por la demanda de Estados Unidos y Brasil, según cifras del sector publicadas esta semana."},
                {"titulo": "Pymes del sur acceden a nuevas líneas de crédito",
                 "resumen": "El programa prioriza a comercios y talleres con menos de cincuenta trabajadores."}]},
        ],
        "clima": [{"dia": f"{DIAS_CORTOS[(hoy + dt.timedelta(i)).weekday()]} {(hoy + dt.timedelta(i)).day}",
                   "icono": "☂☁⛅☀☀☂☁"[i], "temp": f"{6 + i % 3}° / {13 + i % 4}°"} for i in range(7)],
    }


def armar_html(datos, ancho_base, alto_base):
    ahora = dt.datetime.now(ZoneInfo(CONFIG["zona_horaria"]))
    fecha = (f"{CONFIG['ciudad']}, {DIAS[ahora.weekday()]} {ahora.day} de "
             f"{MESES[ahora.month - 1]} de {ahora.year}").upper()
    edicion = "EDICIÓN DE LA MAÑANA" if ahora.hour < 14 else "EDICIÓN DE LA TARDE"
    e = html.escape
    p = datos["principal"]

    foto = (f'<div class="foto" style="background-image:url({p["imagen"]})"></div>'
            if p.get("imagen") else "")
    columnas = "".join(
        f'<div class="col"><div class="kicker">{e(c["seccion"])}</div>'
        + "".join(f'<article><h3>{e(n["titulo"])}</h3><p>{e(limpiar(n["resumen"], 400))}</p></article>'
                  for n in c["noticias"])
        + "</div>" for c in datos["columnas"])
    clima_html = "".join(f"""
      <div class="dia"><b>{e(d['dia'])}</b><span class="ico">{d['icono']}</span>{e(d['temp'])}</div>"""
                         for d in datos["clima"]) or '<div class="dia">Clima no disponible</div>'

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=UnifrakturMaguntia&family=Old+Standard+TT:wght@400;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=block" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ width: {ancho_base}px; height: {alto_base}px; background: #fff; color: #000; overflow: hidden; }}
  body {{ padding: 18px 20px 14px; display: flex; flex-direction: column;
         font-family: 'Source Serif 4', Georgia, serif; }}
  .cabecera {{ text-align: center; }}
  .titulo {{ font-family: 'UnifrakturMaguntia', 'Old English Text MT', serif;
            font-size: 58px; line-height: 1; letter-spacing: .5px; }}
  .fecha {{ margin-top: 8px; border-top: 3px double #000; border-bottom: 1px solid #000;
           padding: 4px 0; font: 700 9.5px 'Old Standard TT', Georgia, serif; letter-spacing: 1px;
           display: flex; justify-content: space-between; }}
  .principal {{ display: flex; gap: 14px; padding: 12px 0; border-bottom: 1px solid #000;
               flex: 0 0 auto; }}
  .foto {{ flex: 0 0 46%; min-height: 230px; background-size: cover; background-position: center;
          filter: grayscale(1) contrast(1.15); }}
  .principal .texto {{ flex: 1; display: flex; flex-direction: column; }}
  .kicker {{ font: 700 8.5px 'Old Standard TT', Georgia, serif; letter-spacing: 1.2px;
            text-transform: uppercase; margin-bottom: 4px; }}
  h2 {{ font: 700 30px/1.08 'Old Standard TT', Georgia, serif; margin-bottom: 8px;
       display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }}
  .sin-foto h2 {{ font-size: 36px; -webkit-line-clamp: 4; }}
  .principal p {{ font-size: 11.5px; line-height: 1.38;
                 display: -webkit-box; -webkit-line-clamp: 7; -webkit-box-orient: vertical; overflow: hidden; }}
  .columnas {{ flex: 1; display: grid; grid-template-columns: repeat(3, 1fr); padding: 10px 0; min-height: 0; }}
  .col {{ padding: 0 10px; border-left: 1px solid #000; overflow: hidden; }}
  .col:first-child {{ padding-left: 0; border-left: 0; }}
  .col:last-child {{ padding-right: 0; }}
  h3 {{ font: 700 16.5px/1.15 'Old Standard TT', Georgia, serif; margin-bottom: 6px;
       display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }}
  .col article + article {{ margin-top: 10px; padding-top: 10px; border-top: 1px solid #999; }}
  .col p {{ font-size: 10px; line-height: 1.38; color: #222;
           display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }}
  .clima {{ border-top: 3px double #000; padding-top: 6px; display: flex; justify-content: space-between; }}
  .dia {{ flex: 1; text-align: center; font-size: 9.5px; line-height: 1.3;
         display: flex; flex-direction: column; align-items: center; }}
  .dia + .dia {{ border-left: 1px solid #999; }}
  .dia b {{ font: 700 8.5px 'Old Standard TT', Georgia, serif; letter-spacing: .8px; }}
  .ico {{ font-size: 17px; line-height: 1.25; font-family: 'Segoe UI Symbol', 'DejaVu Sans', sans-serif; }}
</style></head><body>
  <header class="cabecera">
    <div class="titulo">{e(CONFIG['titulo'])}</div>
    <div class="fecha"><span>{e(fecha)}</span><span>{edicion}</span></div>
  </header>
  <section class="principal {'' if foto else 'sin-foto'}">
    {foto}
    <div class="texto">
      <div class="kicker">{e(p['seccion'])}</div>
      <h2>{e(p['titulo'])}</h2>
      <p>{e(limpiar(p['resumen'], 700))}</p>
    </div>
  </section>
  <section class="columnas">{columnas}</section>
  <footer class="clima">{clima_html}</footer>
</body></html>"""


AJUSTAR_COLUMNAS = """
document.querySelectorAll('.col').forEach(col => {
  const fondo = col.getBoundingClientRect().bottom;
  let lleno = false;
  col.querySelectorAll('article').forEach(art => {
    if (lleno) { art.remove(); return; }
    if (art.getBoundingClientRect().bottom <= fondo) return;
    const h = art.querySelector('h3'), p = art.querySelector('p');
    const linea = parseFloat(getComputedStyle(p).lineHeight);
    const lineas = Math.floor((fondo - p.getBoundingClientRect().top) / linea);
    if (h.getBoundingClientRect().bottom < fondo && lineas >= 2) {
      p.style.webkitLineClamp = lineas;
    } else {
      art.remove();
    }
    lleno = true;
  });
});
"""


def generar(ejemplo=False):
    from PIL import Image
    from playwright.sync_api import sync_playwright

    ancho, alto = MODELOS[CONFIG["modelo_kindle"]]
    ancho_base = int(CONFIG.get("ancho_diseno", 520))  # menor = letras más grandes
    alto_base = round(ancho_base * alto / ancho)
    escala = ancho / ancho_base

    datos = datos_ejemplo() if ejemplo else datos_reales()
    pagina_html = armar_html(datos, ancho_base, alto_base)
    SALIDA.mkdir(exist_ok=True)
    (SALIDA / "portada.html").write_text(pagina_html, encoding="utf-8")

    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": ancho_base, "height": alto_base},
                           device_scale_factor=escala)
        pag.set_content(pagina_html, wait_until="load", timeout=60000)
        try:
            pag.evaluate("document.fonts.ready")
        except Exception:
            pass
        # Ya con las fuentes cargadas: deja en cada columna solo las noticias que caben,
        # y recorta el resumen de la última para que no quede cortado a la mitad.
        pag.evaluate(AJUSTAR_COLUMNAS)
        tmp = SALIDA / "captura.png"
        pag.screenshot(path=str(tmp), full_page=False)
        nav.close()

    img = Image.open(tmp).convert("L").resize((ancho, alto))
    destino = SALIDA / "portada.png"
    img.save(SALIDA / "portada.tmp.png", optimize=True)
    (SALIDA / "portada.tmp.png").replace(destino)  # reemplazo atómico: el Kindle nunca baja un archivo a medias
    tmp.unlink(missing_ok=True)
    print(f"Portada lista: {destino} ({ancho}x{alto})")
    return destino


# ---------------------------------------------------------------- servidor

def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def servir():
    class Manejador(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(SALIDA), **k)

        def log_message(self, fmt, *args):
            print(f"  [{dt.datetime.now():%H:%M}] {self.address_string()} pidió {self.path}")

    srv = http.server.ThreadingHTTPServer(("0.0.0.0", CONFIG["puerto"]), Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"\nEl Kindle debe descargar: http://{ip_local()}:{CONFIG['puerto']}/portada.png\n")


def segundos_hasta_proxima():
    zona = ZoneInfo(CONFIG["zona_horaria"])
    ahora = dt.datetime.now(zona)
    candidatos = []
    for dias in (0, 1):
        for h in CONFIG["horas_actualizacion"]:
            t = (ahora + dt.timedelta(days=dias)).replace(hour=h, minute=0, second=0, microsecond=0)
            if t > ahora:
                candidatos.append(t)
    return (min(candidatos) - ahora).total_seconds()


def probar_fuentes():
    for clave, s in CONFIG["secciones"].items():
        print(f"\n{s['nombre']}:")
        for url in s["fuentes"]:
            try:
                n = leer_rss(url)
                foto = sum(1 for x in n if x["imagen"])
                print(f"  OK   {url}  ({len(n)} noticias, {foto} con foto)")
            except Exception as e:
                print(f"  FALLA {url}  ({e.__class__.__name__}: {e})")


def main():
    args = sys.argv[1:]
    if "--probar" in args:
        return probar_fuentes()
    if "--ejemplo" in args:
        return generar(ejemplo=True)
    if "--una-vez" in args:
        return generar()

    SALIDA.mkdir(exist_ok=True)
    generar()
    servir()
    while True:
        espera = segundos_hasta_proxima()
        print(f"Próxima actualización en {espera / 3600:.1f} h. Deja esta ventana abierta.")
        time.sleep(espera + 5)
        try:
            generar()
        except Exception as e:
            print(f"No se pudo actualizar ({e}). Se mantiene la portada anterior.")


if __name__ == "__main__":
    main()
