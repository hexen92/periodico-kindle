"""
Arma el periódico del día como libro EPUB: un capítulo por sección,
con índice navegable y la portada del día como tapa.
"""

import datetime as dt
import html
import io
import re
import uuid
import zipfile
from zoneinfo import ZoneInfo

import periodico as P

e = html.escape


# --------------------------------------------------------- texto e imágenes

def parrafos(html_crudo, resumen):
    """Convierte el HTML del RSS en una lista de párrafos de texto limpio."""
    crudo = html_crudo or ""
    # quita bloques que nunca son parte del artículo
    crudo = re.sub(r"(?is)<(script|style|figure|figcaption|iframe|form)[^>]*>.*?</\1>", " ", crudo)
    bloques = re.findall(r"(?is)<(?:p|h[2-4]|li|blockquote)[^>]*>(.*?)</(?:p|h[2-4]|li|blockquote)>", crudo)
    if not bloques:
        bloques = re.split(r"(?i)<br\s*/?>\s*<br\s*/?>|\n\s*\n", crudo)
    salida = []
    for b in bloques:
        t = P.limpiar(b)
        if len(t) < 2 or t in salida:
            continue
        if re.match(r"(?i)^(the post|la entrada|leer m[aá]s|seguir leyendo|continue reading|read more)\b", t):
            continue
        salida.append(t)
    if not salida and resumen:
        salida = [resumen]
    return salida


def imagen_para_libro(url):
    """Descarga y deja la foto lista para e-ink: gris, máx. 800 px, JPEG liviano."""
    if not url:
        return None
    try:
        from PIL import Image
        datos = P.descargar(url, 20)
        im = Image.open(io.BytesIO(datos)).convert("L")
        if im.width < 200 or im.height < 120:  # íconos y píxeles de seguimiento
            return None
        im.thumbnail((800, 800))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


# ------------------------------------------------------------------- EPUB

CSS = """
body { font-family: serif; margin: 0 0.4em; }
h1 { font-size: 1.9em; text-align: center; margin: 0.6em 0 0.2em; letter-spacing: 0.05em; }
.fecha { text-align: center; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.15em;
         border-top: 3px double #000; border-bottom: 1px solid #000; padding: 0.3em 0; margin-bottom: 1.2em; }
h2 { font-size: 1.3em; line-height: 1.2; margin: 1.4em 0 0.2em; page-break-after: avoid; }
.fuente { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.1em; color: #444; margin: 0 0 0.6em; }
p { text-indent: 0; margin: 0 0 0.7em; line-height: 1.4; text-align: justify; }
img { max-width: 100%; display: block; margin: 0.4em auto 0.8em; }
hr { border: 0; border-top: 1px solid #888; margin: 1.4em 25%; }
.sumario li { margin-bottom: 0.4em; }
.tapa { text-align: center; margin: 0; padding: 0; }
.tapa img { max-width: 100%; max-height: 100%; margin: 0 auto; }
"""


def _xhtml(titulo, cuerpo):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="es" xml:lang="es">
<head><meta charset="utf-8"/><title>{e(titulo)}</title>
<link rel="stylesheet" type="text/css" href="estilo.css"/></head>
<body>{cuerpo}</body></html>"""


def generar_libro(destino, portada_png=None):
    conf = P.CONFIG.get("libro", {})
    por_seccion = int(conf.get("noticias_por_seccion", 10))
    con_fotos = conf.get("fotos", True)

    ahora = dt.datetime.now(ZoneInfo(P.CONFIG["zona_horaria"]))
    edicion = "mañana" if ahora.hour < 14 else "tarde"
    fecha_larga = f"{P.DIAS[ahora.weekday()]} {ahora.day} de {P.MESES[ahora.month - 1]} de {ahora.year}"
    titulo_libro = f"{P.CONFIG.get('titulo', 'Periódico')} · {ahora.day} {P.MESES[ahora.month - 1][:3]} ({edicion})"

    print("Armando el libro…")
    capitulos, imagenes = [], {}
    for i, sec in enumerate(conf.get("secciones", []), 1):
        noticias = [n for n in P.noticias_de(sec, por_seccion) if n.get("fuente")]
        arts = []
        for j, n in enumerate(noticias, 1):
            img_ref = None
            if con_fotos and n.get("imagen"):
                datos = imagen_para_libro(n["imagen"])
                if datos:
                    img_ref = f"img/s{i}n{j}.jpg"
                    imagenes[img_ref] = datos
            arts.append({**n, "id": f"n{j}", "img": img_ref,
                         "parrafos": parrafos(n.get("html"), n.get("resumen"))})
        capitulos.append({"archivo": f"seccion{i}.xhtml", "nombre": sec["nombre"], "arts": arts})
        print(f"  · {sec['nombre']}: {len(arts)} noticias")

    # ---- páginas
    paginas = {}
    sumario = "".join(
        f'<li><a href="{c["archivo"]}">{e(c["nombre"])}</a> ({len(c["arts"])})</li>' for c in capitulos)
    paginas["inicio.xhtml"] = _xhtml(titulo_libro, f"""
<h1>{e(P.CONFIG.get('titulo', 'Periódico'))}</h1>
<div class="fecha">{e(P.CONFIG['ciudad'])} · {e(fecha_larga)} · edición de la {edicion}</div>
<ul class="sumario">{sumario}</ul>""")

    for c in capitulos:
        cuerpo = [f"<h1>{e(c['nombre'])}</h1>", f'<div class="fecha">{e(fecha_larga)}</div>']
        if not c["arts"]:
            cuerpo.append("<p>Sin noticias disponibles: ninguna fuente respondió.</p>")
        for k, a in enumerate(c["arts"]):
            if k:
                cuerpo.append("<hr/>")
            cuerpo.append(f'<h2 id="{a["id"]}">{e(a["titulo"])}</h2>')
            cuerpo.append(f'<p class="fuente">{e(a["fuente"])}</p>')
            if a["img"]:
                cuerpo.append(f'<img src="{a["img"]}" alt=""/>')
            cuerpo.extend(f"<p>{e(t)}</p>" for t in a["parrafos"])
        paginas[c["archivo"]] = _xhtml(c["nombre"], "\n".join(cuerpo))

    if portada_png:
        paginas["tapa.xhtml"] = _xhtml("Portada", '<div class="tapa"><img src="tapa.png" alt="Portada"/></div>')

    # ---- índice (EPUB 3 + NCX para lectores antiguos)
    nav_items = "".join(
        f'<li><a href="{c["archivo"]}">{e(c["nombre"])}</a>'
        + ("<ol>" + "".join(f'<li><a href="{c["archivo"]}#{a["id"]}">{e(a["titulo"])}</a></li>'
                            for a in c["arts"]) + "</ol>" if c["arts"] else "")
        + "</li>" for c in capitulos)
    nav = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="es" xml:lang="es">
<head><meta charset="utf-8"/><title>Índice</title></head>
<body><nav epub:type="toc" id="toc"><h1>Índice</h1><ol>{nav_items}</ol></nav></body></html>"""

    orden, puntos = [1], []

    def punto(texto, src, hijos=""):
        n = orden[0]; orden[0] += 1
        return (f'<navPoint id="p{n}" playOrder="{n}"><navLabel><text>{e(texto)}</text></navLabel>'
                f'<content src="{src}"/>{hijos}</navPoint>')
    for c in capitulos:
        cab = punto(c["nombre"], c["archivo"], "")[:-len("</navPoint>")]
        hijos = "".join(punto(a["titulo"], f'{c["archivo"]}#{a["id"]}') for a in c["arts"])
        puntos.append(cab + hijos + "</navPoint>")

    ident = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'periodico-' + ahora.strftime('%Y%m%d%H'))}"
    ncx = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{ident}"/></head>
<docTitle><text>{e(titulo_libro)}</text></docTitle>
<navMap>{''.join(puntos)}</navMap></ncx>"""

    # ---- manifiesto
    spine = (["tapa.xhtml"] if portada_png else []) + ["inicio.xhtml"] + [c["archivo"] for c in capitulos]
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="estilo.css" media-type="text/css"/>',
    ]
    for nombre in spine:
        manifest.append(f'<item id="{nombre.split(".")[0]}" href="{nombre}" media-type="application/xhtml+xml"/>')
    if portada_png:
        manifest.append('<item id="tapa-img" href="tapa.png" media-type="image/png" properties="cover-image"/>')
    for k, ref in enumerate(imagenes):
        manifest.append(f'<item id="im{k}" href="{ref}" media-type="image/jpeg"/>')

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="es">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:identifier id="uid">{ident}</dc:identifier>
  <dc:title>{e(titulo_libro)}</dc:title>
  <dc:language>es</dc:language>
  <dc:creator>{e(P.CONFIG.get('titulo', 'Periódico'))}</dc:creator>
  <dc:date>{ahora.date().isoformat()}</dc:date>
  <meta property="dcterms:modified">{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}</meta>
  {'<meta name="cover" content="tapa-img"/>' if portada_png else ''}
</metadata>
<manifest>{''.join(manifest)}</manifest>
<spine toc="ncx">{''.join(f'<itemref idref="{n.split(".")[0]}"/>' for n in spine)}</spine>
</package>"""

    with zipfile.ZipFile(destino, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""", compress_type=zipfile.ZIP_DEFLATED)
        archivos = {"content.opf": opf, "nav.xhtml": nav, "toc.ncx": ncx, "estilo.css": CSS, **paginas}
        for nombre, texto in archivos.items():
            z.writestr("OEBPS/" + nombre, texto, compress_type=zipfile.ZIP_DEFLATED)
        if portada_png:
            z.write(portada_png, "OEBPS/tapa.png", compress_type=zipfile.ZIP_DEFLATED)
        for ref, datos in imagenes.items():
            z.writestr("OEBPS/" + ref, datos, compress_type=zipfile.ZIP_DEFLATED)
    print(f"Libro listo: {destino}")
    return destino
