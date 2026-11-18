import csv
import io
import zipfile
import json
import os
import hashlib
import secrets
from datetime import date, datetime
from pathlib import Path

import qrcode
from flask import (Flask, Response, abort, redirect, render_template_string,
                   request, send_from_directory, session, url_for)

BASE = Path(__file__).parent
ARCHIVO = BASE / "carnets.json"
FOTOS = BASE / "fotos"
FOTOS.mkdir(exist_ok=True)
LOGO = BASE / "logo.png"
FIRMA = BASE / "firma.png"
AJUSTES_ARCHIVO = BASE / "ajustes.json"

# Contraseña del panel. Cámbiala aquí o con la variable de entorno ADMIN_PASSWORD.
ADMIN_USER = os.environ.get("ADMIN_USER", "Elpope")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "popeye26")
# Dirección pública para los QR. Si la dejas vacía, usa la dirección desde donde abras el panel.
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
ENTIDAD = "Municipalidad de Villa El Salvador"

DEFECTO = {
    "entidad": ENTIDAD,
    "titulo": "Verificación de carnet de sanidad",
    "pie": "Los datos mostrados deben coincidir con el carnet físico.",
    "marca_opacidad": 12,   # 0 a 40 (%)
    "marca_tamano": 70,     # 20 a 150
    "marca_posicion": 50,   # 0 (arriba) a 100 (abajo)
    "marca_carnet": False,  # mostrar también en el carnet impreso
    "carnet_entidad": "MUNICIPALIDAD DISTRITAL DE VILLA EL SALVADOR",  # texto sobre la firma
}


def cargar_ajustes():
    a = dict(DEFECTO)
    if AJUSTES_ARCHIVO.exists():
        with open(AJUSTES_ARCHIVO, encoding="utf-8") as f:
            a.update(json.load(f))
    return a


def vista(plantilla, **kw):
    return render_template_string(plantilla, a=cargar_ajustes(), logo=LOGO.exists(), **kw)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    (ADMIN_PASSWORD + "carnets-sanidad").encode()).hexdigest()

CSS = """
:root{--bg:#f3f6f4;--card:#fff;--ink:#16302b;--mute:#5d716c;--line:#d6e0dc;--ok:#1b7a4b;--okbg:#e2f3ea;--bad:#a63232;--badbg:#f8e4e4;--acc:#1b7a4b}
@media (prefers-color-scheme:dark){:root{--bg:#0f1a17;--card:#172622;--ink:#e6f0ec;--mute:#9bb0aa;--line:#2a3f39;--ok:#6fd6a2;--okbg:#17372a;--bad:#ff9b9b;--badbg:#3b1d1d;--acc:#6fd6a2}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Georgia,"Times New Roman",serif;padding:20px}
main{max-width:460px;margin:0 auto}
header{text-align:center;margin:8px 0 18px}
header p{margin:0;color:var(--mute);font-size:.9rem}
header h1{margin:4px 0 0;font-size:1.25rem;letter-spacing:.04em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px}
.status{border-radius:8px;padding:14px;text-align:center;font-size:1.5rem;font-weight:bold;letter-spacing:.06em}
.status small{display:block;font-size:.8rem;font-weight:normal;letter-spacing:0;margin-top:4px}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
.name{font-size:1.3rem;text-align:center;margin:18px 0 0;font-weight:bold}
dl{margin:18px 0 0}
.row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
.row:last-child{border:0}
dt{color:var(--mute);font-size:.9rem}
dd{margin:0;font-weight:bold;text-align:right}
.foot{margin-top:14px;text-align:center;color:var(--mute);font-size:.8rem}
"""

PAGINA = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ a.titulo }}</title><style>""" + CSS + """

:root{--bg:#fff;--card:#fff;--ink:#16302b;--mute:#5d716c;--line:#d6e0dc;--ok:#1b7a4b;--okbg:#e2f3ea;--bad:#a63232;--badbg:#f8e4e4}
@media (prefers-color-scheme:dark){:root{--bg:#fff;--card:#fff;--ink:#16302b;--mute:#5d716c;--line:#d6e0dc;--ok:#1b7a4b;--okbg:#e2f3ea;--bad:#a63232;--badbg:#f8e4e4}}
body{background:#fff}
.marca{position:fixed;left:50%;top:{{ a.marca_posicion }}%;transform:translate(-50%,-50%);width:{{ a.marca_tamano }}vmin;max-width:150vw;opacity:{{ a.marca_opacidad / 100 }};pointer-events:none;z-index:0}
main{position:relative;z-index:1}
.card{background:color-mix(in srgb,var(--card) 72%,transparent)}
</style></head><body>
{% if logo %}<img class="marca" src="{{ url_for('logo') }}" alt="">{% endif %}<main>
{% if previa and c %}<div style="text-align:center;margin:4px 0 14px;font-size:.9rem;font-family:Arial,sans-serif">
<a style="color:var(--ok)" href="{{ url_for('admin') }}">← Panel</a> ·
<a style="color:var(--ok)" href="{{ url_for('editar', codigo=codigo) }}">Editar</a> ·
<a style="color:var(--ok)" href="{{ url_for('qr_png', codigo=codigo) }}" target="_blank">Ver QR</a> ·
<a style="color:var(--ok)" href="{{ url_for('carnet', codigo=codigo) }}">Carnet imprimible</a></div>{% endif %}
<header>{% if logo %}<img src="{{ url_for('logo') }}" alt="" style="height:110px;max-width:80%;object-fit:contain;margin-bottom:8px">{% endif %}<p>{{ a.entidad }}</p><h1>{{ a.titulo }}</h1></header>
<div class="card">
{% if c %}
  <div class="status {{ 'ok' if c.vigente else 'bad' }}">{{ 'VIGENTE' if c.vigente else 'VENCIDO / NO APTO' }}
    <small>Condición: {{ c.condicion }}</small></div>
  <p class="name">{{ c.nombres }} {{ c.apellidos }}</p>
  <dl>
    <div class="row"><dt>DNI</dt><dd>{{ c.dni }}</dd></div>
    <div class="row"><dt>Fecha de emisión</dt><dd>{{ c.emision }}</dd></div>
    <div class="row"><dt>Fecha de vencimiento</dt><dd>{{ c.vence }}</dd></div>
    {% if c.medico %}<div class="row"><dt>Médico</dt><dd>{{ c.medico }}</dd></div>{% endif %}
  </dl>
{% else %}
  <div class="status bad">NO ENCONTRADO<small>El código no corresponde a ningún carnet registrado.</small></div>
{% endif %}
</div><p class="foot">{{ a.pie }}</p></main></body></html>"""


FORM_CAMPOS = """
<label>Apellidos<input name="apellidos" value="{{ v.apellidos }}" required></label>
<label>Nombres<input name="nombres" value="{{ v.nombres }}" required></label>
<label>DNI<input name="dni" value="{{ v.dni }}" required pattern="[0-9]{8}" maxlength="8" title="8 dígitos"></label>
<label>Grupo sanguíneo<input name="grupo" value="{{ v.grupo }}" placeholder="RH +"></label>
<label>Ex. pulmones<select name="pulmones">{% for o in ['NEGATIVO','POSITIVO'] %}<option {{ 'selected' if v.pulmones == o }}>{{ o }}</option>{% endfor %}</select></label>
<label>Ex. VDRL<select name="vdrl">{% for o in ['NO REACTIVO','REACTIVO'] %}<option {{ 'selected' if v.vdrl == o }}>{{ o }}</option>{% endfor %}</select></label>
<label>Condición<select name="condicion">{% for o in ['APTO','NO APTO'] %}<option {{ 'selected' if v.condicion == o }}>{{ o }}</option>{% endfor %}</select></label>
<label>Fecha de emisión<input type="date" name="emision" value="{{ v.emision }}" required></label>
<label>Fecha de vencimiento (vacío = 1 año)<input type="date" name="vence" value="{{ v.vence }}"></label>
<label>Médico (opcional)<input name="medico" value="{{ v.medico }}"></label>
<label>Foto {% if v.foto %}(ya tiene; sube otra para cambiarla){% endif %}<input type="file" name="foto" accept="image/*"></label>
"""

ADMIN = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de carnets</title><style>""" + CSS + """
main{max-width:900px}
form.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
label{font-size:.85rem;color:var(--mute);display:flex;flex-direction:column;gap:4px}
input,select{padding:9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:10px 16px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
@media (prefers-color-scheme:dark){button,.btn{color:#0f1a17}}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:.9rem}
th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}
.wrap{overflow-x:auto}
a{color:var(--acc)}
h2{margin:26px 0 10px;font-size:1.1rem}
.msg{background:var(--okbg);color:var(--ok);padding:10px;border-radius:6px;margin-bottom:14px}
</style></head><body><main>
<header><p>{{ a.entidad }}</p><h1>Panel de carnets de sanidad</h1><p style="margin-top:8px"><a href="{{ url_for('ajustes') }}">⚙ Ajustes, logo y marca de agua</a></p></header>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
<div class="card">
<h2 style="margin-top:0">Nuevo carnet</h2>
<form class="f" method="post" action="{{ url_for('nuevo') }}" enctype="multipart/form-data">
""" + FORM_CAMPOS + """
<div style="display:flex;align-items:end"><button type="submit">Guardar y ver carnet</button></div>
</form></div>

<div class="card" style="margin-top:16px">
<h2 style="margin-top:0">Importar muchos desde Excel / CSV</h2>
<p class="foot" style="text-align:left">Columnas: apellidos, nombres, dni, grupo, pulmones, vdrl, condicion, emision, vence, medico (fechas AAAA-MM-DD). Guarda el Excel como "CSV UTF-8".</p>
<form method="post" action="{{ url_for('importar') }}" enctype="multipart/form-data" style="display:flex;gap:10px;flex-wrap:wrap">
<input type="file" name="archivo" accept=".csv" required><button type="submit">Importar</button>
<a class="btn" href="{{ url_for('plantilla') }}">Descargar plantilla</a></form></div>

<h2>Carnets registrados ({{ total }}) <a class="btn" style="font-size:.8rem;margin-left:10px" href="{{ url_for('carnets_zip') }}">Descargar todos (ZIP)</a></h2>
<form method="get" style="display:flex;gap:10px"><input name="q" value="{{ q }}" placeholder="Buscar por nombre, apellido o DNI" style="flex:1"><button>Buscar</button></form>
<div class="wrap"><table><tr><th>Código</th><th>Nombre</th><th>DNI</th><th>Vence</th><th></th></tr>
{% for k, r in filas %}
<tr><td>{{ k }}</td><td>{{ r.apellidos }}, {{ r.nombres }}</td><td>{{ r.dni }}</td><td>{{ r.vence }}</td>
<td style="white-space:nowrap"><a href="{{ url_for('carnet', codigo=k) }}">Carnet / descargar</a> · <a href="{{ url_for('ver_carnet', codigo=k, previa=1) }}">Ver página</a> · <a href="{{ url_for('editar', codigo=k) }}">Editar</a></td></tr>
{% endfor %}</table></div>
</main></body></html>"""


EDITAR = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Editar {{ codigo }}</title><style>""" + CSS + """
main{max-width:900px}
form.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
label{font-size:.85rem;color:var(--mute);display:flex;flex-direction:column;gap:4px}
input,select{padding:9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
button,.btn{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:10px 16px;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
.peligro{background:var(--bad)}
a{color:var(--acc)}
</style></head><body><main>
<header><p>{{ a.entidad }}</p><h1>Editar carnet {{ codigo }}</h1><p><a href="{{ url_for('admin') }}">← Volver al panel</a></p></header>
<div class="card">
<form class="f" method="post" enctype="multipart/form-data">
""" + FORM_CAMPOS + """
<div style="display:flex;align-items:end;gap:10px"><button type="submit">Guardar cambios</button></div>
</form>
<form method="post" action="{{ url_for('eliminar', codigo=codigo) }}" style="margin-top:18px" onsubmit="return confirm('¿Eliminar este carnet? Su QR dejará de funcionar.')">
<button class="peligro" type="submit">Eliminar carnet</button></form>
</div></main></body></html>"""

AJUSTES = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ajustes</title><style>""" + CSS + """
main{max-width:900px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
label{font-size:.85rem;color:var(--mute);display:flex;flex-direction:column;gap:4px;margin-bottom:12px}
input[type=text],input[type=file]{padding:9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);font:inherit}
input[type=range]{width:100%}
button{background:var(--acc);color:#fff;border:0;border-radius:6px;padding:10px 16px;font:inherit;cursor:pointer}
a{color:var(--acc)}
.msg{background:var(--okbg);color:var(--ok);padding:10px;border-radius:6px;margin-bottom:14px}
.pv{position:relative;overflow:hidden;height:380px;border:1px solid var(--line);border-radius:10px;background:var(--bg)}
.pv img{position:absolute;left:50%;transform:translate(-50%,-50%);pointer-events:none}
.pv .c{position:relative;margin:18px;padding:14px;border:1px solid var(--line);border-radius:8px;text-align:center;background:color-mix(in srgb,var(--card) 72%,transparent)}
</style></head><body><main>
<header><p>{{ a.entidad }}</p><h1>Ajustes de la página</h1><p><a href="{{ url_for('admin') }}">← Volver al panel</a></p></header>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
<form method="post" enctype="multipart/form-data">
<div class="g">
<div class="card">
<label>Nombre de la entidad<input type="text" name="entidad" value="{{ a.entidad }}"></label>
<label>Título de la página<input type="text" name="titulo" value="{{ a.titulo }}"></label>
<label>Texto al pie<input type="text" name="pie" value="{{ a.pie }}"></label>
<label>Texto sobre la firma (carnet)<input type="text" name="carnet_entidad" value="{{ a.carnet_entidad }}"></label>
<label>Firma y sello del médico (PNG o JPG){% if firma %} — ya hay una cargada{% endif %}<input type="file" name="firma" accept="image/*"></label>
<label>Logo / insignia (PNG o JPG){% if logo %} — ya hay uno cargado{% endif %}<input type="file" name="logo" accept="image/*"></label>
<label>Opacidad de la marca de agua: <b id="o_v">{{ a.marca_opacidad }}</b>%<input type="range" id="o" name="marca_opacidad" min="0" max="40" value="{{ a.marca_opacidad }}"></label>
<label>Tamaño: <b id="t_v">{{ a.marca_tamano }}</b><input type="range" id="t" name="marca_tamano" min="20" max="150" value="{{ a.marca_tamano }}"></label>
<label>Posición vertical: <b id="p_v">{{ a.marca_posicion }}</b>%<input type="range" id="p" name="marca_posicion" min="0" max="100" value="{{ a.marca_posicion }}"></label>
<label style="flex-direction:row;align-items:center;gap:8px"><input type="checkbox" name="marca_carnet" {{ 'checked' if a.marca_carnet }}> Mostrar también en el carnet impreso</label>
<button type="submit">Guardar ajustes</button>
</div>
<div><p class="foot" style="text-align:left;margin-top:0">Vista previa (así se ve al escanear el QR)</p>
<div class="pv" id="pv">{% if logo %}<img id="pvi" src="{{ url_for('logo') }}?v={{ ver }}" alt="">{% endif %}
<div class="c"><b style="color:var(--ok)">VIGENTE</b><br>NOMBRE APELLIDO<br><small>DNI 12****78 · 04/11/2026 – 10/11/2027</small></div></div></div>
</div></form>
<script>
var pv=document.getElementById('pv'),im=document.getElementById('pvi');
function ap(){var o=document.getElementById('o').value,t=document.getElementById('t').value,p=document.getElementById('p').value;
document.getElementById('o_v').textContent=o;document.getElementById('t_v').textContent=t;document.getElementById('p_v').textContent=p;
if(im){im.style.opacity=o/100;im.style.width=(t/100*Math.min(pv.clientWidth,pv.clientHeight))+'px';im.style.top=p+'%';}}
['o','t','p'].forEach(function(i){document.getElementById(i).addEventListener('input',ap)});ap();
</script></main></body></html>"""

CARNET = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carnet {{ codigo }}</title>
<style>
@page{size:A5 portrait;margin:0}
body{margin:0;background:#e9e9e9;font-family:Arial,sans-serif;color:#111}
.bar{text-align:center;padding:12px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap;align-items:center}
.bar a,.bar button{padding:10px 16px;font:inherit;cursor:pointer;background:#1b7a4b;color:#fff;border:0;border-radius:6px;text-decoration:none}
.bar a.s{background:#fff;color:#1b7a4b;border:1px solid #1b7a4b}
.hoja{width:min(560px,96vw);margin:6px auto 24px;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.2)}
.hoja img{display:block;width:100%}
@media print{body{background:#fff}.bar{display:none}.hoja{width:100%;margin:0;box-shadow:none}}
</style></head><body>
<div class="bar">
<a href="{{ url_for('carnet_pdf', codigo=codigo) }}">Descargar PDF</a>
<a href="{{ url_for('carnet_png', codigo=codigo) }}?descargar=1">Descargar imagen PNG</a>
<button onclick="window.print()">Imprimir</button>
<a class="s" href="{{ url_for('editar', codigo=codigo) }}">Editar datos</a>
<a class="s" href="{{ url_for('admin') }}">← Panel</a></div>
<div class="hoja"><img src="{{ url_for('carnet_png', codigo=codigo) }}?v={{ ver }}" alt="Carnet {{ codigo }}"></div>
</body></html>"""


# ---------------- Imagen del carnet (misma disposición que el modelo de Canva) ----------------
ANCHO, ALTO = 1200, 1660
TEXTO = (25, 25, 25)

F_REG = ["C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/georgia.ttf",
         "/Library/Fonts/Times New Roman.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "DejaVuSerif.ttf"]
F_NEG = ["C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/georgiab.ttf",
         "/Library/Fonts/Times New Roman Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"]


def fuente(rutas, tam):
    from PIL import ImageFont
    for r in rutas:
        try:
            return ImageFont.truetype(r, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def texto(d, x, y, t, f, sep=0, centro=False, fill=TEXTO):
    """Dibuja texto con separación entre letras. y = centro vertical del texto."""
    ancho = sum(d.textlength(c, font=f) for c in t) + sep * (len(t) - 1)
    if centro:
        x -= ancho / 2
    for c in t:
        d.text((x, y), c, font=f, fill=fill, anchor="lm")
        x += d.textlength(c, font=f) + sep


def pegar_centrado(lienzo, img, cx, cy, caja_w, caja_h):
    from PIL import Image
    img = img.convert("RGBA")
    esc = min(caja_w / img.width, caja_h / img.height)
    img = img.resize((max(1, int(img.width * esc)), max(1, int(img.height * esc))), Image.LANCZOS)
    lienzo.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))


def dibujar_carnet(codigo, r, a, url_qr):
    from PIL import Image, ImageDraw
    lienzo = Image.new("RGBA", (ANCHO, ALTO), "white")

    # marca de agua opcional
    if LOGO.exists() and a.get("marca_carnet"):
        wm = Image.open(LOGO).convert("RGBA")
        esc = ANCHO * a["marca_tamano"] / 100 / wm.width
        wm = wm.resize((int(wm.width * esc), int(wm.height * esc)), Image.LANCZOS)
        wm.putalpha(wm.split()[3].point(lambda p: int(p * a["marca_opacidad"] / 100)))
        lienzo.alpha_composite(wm, (int(ANCHO / 2 - wm.width / 2),
                                    int(ALTO * a["marca_posicion"] / 100 - wm.height / 2)))

    d = ImageDraw.Draw(lienzo)
    if LOGO.exists():
        pegar_centrado(lienzo, Image.open(LOGO), 600, 112, 520, 205)

    # líneas y título
    d.line([(138, 258), (1081, 258)], fill=(70, 70, 70), width=2)
    texto(d, 600, 292, "CARNET DE SANIDAD", fuente(F_REG, 31), sep=4.5, centro=True)

    # datos de la persona
    f_lab, f_val = fuente(F_REG, 23), fuente(F_NEG, 32)
    filas = [("APELLIDOS", r["apellidos"], 416, 448), ("NOMBRES", r["nombres"], 488, 524),
             ("D.N.I", r["dni"], 566, 596), ("GRUPO SANGUÍNEO", r.get("grupo", ""), 628, 662),
             ("EX. PULMONES", r.get("pulmones", ""), 704, 738), ("EX. VDRL", r.get("vdrl", ""), 780, 821)]
    for etiqueta, valor, ye, yv in filas:
        texto(d, 198, ye, etiqueta, f_lab, sep=2.6)
        texto(d, 240, yv, valor, f_val)

    # QR único de la persona
    qr_buf = io.BytesIO()
    qrcode.make(url_qr).save(qr_buf, format="PNG")
    qr_buf.seek(0)
    qr = Image.open(qr_buf).convert("RGB").resize((196, 196), Image.NEAREST)
    lienzo.paste(qr, (884, 408))

    # foto
    fx, fy, fw, fh = 552, 667, 202, 232
    if r.get("foto") and (FOTOS / r["foto"]).exists():
        ft = Image.open(FOTOS / r["foto"]).convert("RGB")
        esc = max(fw / ft.width, fh / ft.height)
        ft = ft.resize((int(ft.width * esc) + 1, int(ft.height * esc) + 1), Image.LANCZOS)
        izq, arr = (ft.width - fw) // 2, (ft.height - fh) // 4
        lienzo.paste(ft.crop((izq, arr, izq + fw, arr + fh)), (fx, fy))
    else:
        d.rectangle([fx, fy, fx + fw, fy + fh], outline=(190, 190, 190), width=2)
        texto(d, fx + fw / 2, fy + fh / 2, "FOTO", fuente(F_REG, 26), centro=True, fill=(170, 170, 170))

    # condición
    texto(d, 653, 957, "CONDICIÓN", fuente(F_REG, 20), sep=1.8, centro=True)
    texto(d, 653, 992, r["condicion"], fuente(F_NEG, 38), centro=True)

    # fechas
    d.line([(159, 1044), (1106, 1044)], fill=(70, 70, 70), width=2)
    f_fecha = fuente(F_REG, 30)
    texto(d, 184, 1092, "Fecha: " + datetime.strptime(r["emision"], "%Y-%m-%d").strftime("%d-%m-%Y"), f_fecha)
    texto(d, 184, 1128, "Expira: " + datetime.strptime(r["vence"], "%Y-%m-%d").strftime("%d-%m-%Y"), f_fecha)

    # entidad y firma
    texto(d, 667, 1212, a["carnet_entidad"].upper(), fuente(F_REG, 23), sep=1.2, centro=True)
    if FIRMA.exists():
        pegar_centrado(lienzo, Image.open(FIRMA), 625, 1377, 360, 225)
    return lienzo.convert("RGB")


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def imagen_de(codigo):
    r = cargar().get(codigo)
    if not r:
        abort(404)
    return r, dibujar_carnet(codigo, r, cargar_ajustes(), f"{base_publica()}/c/{codigo}")


def cargar():
    if not ARCHIVO.exists():
        return {}
    with open(ARCHIVO, encoding="utf-8") as f:
        return json.load(f)


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def fmt(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def siguiente_codigo(datos):
    n = 0
    for k in datos:
        if k.startswith("C") and k[1:].isdigit():
            n = max(n, int(k[1:]))
    return f"C{n + 1:04d}"


def mas_un_anio(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    try:
        return d.replace(year=d.year + 1).isoformat()
    except ValueError:  # 29 de febrero
        return d.replace(year=d.year + 1, day=28).isoformat()


def pedir_clave():
    return Response("Acceso restringido", 401,
                    {"WWW-Authenticate": 'Basic realm="Panel de carnets"'})


def autorizado():
    a = request.authorization
    return bool(a and secrets.compare_digest(a.username or "", ADMIN_USER)
                and secrets.compare_digest(a.password or "", ADMIN_PASSWORD))


@app.before_request
def proteger():
    if autorizado():
        session["admin"] = True  # solo el médico: así ve la barra de enlaces en la página
    publicas = ("ver_carnet", "logo")
    if request.endpoint in publicas or request.endpoint == "static":
        return None
    if not autorizado():
        return pedir_clave()


def base_publica():
    return BASE_URL or request.host_url.rstrip("/")


def registrar(datos, f, foto=None):
    codigo = siguiente_codigo(datos)
    emision = f["emision"]
    datos[codigo] = {
        "apellidos": f["apellidos"].strip().upper(),
        "nombres": f["nombres"].strip().upper(),
        "dni": f["dni"].strip(),
        "grupo": f.get("grupo", "").strip(),
        "pulmones": f.get("pulmones", "NEGATIVO").strip().upper() or "NEGATIVO",
        "vdrl": f.get("vdrl", "NO REACTIVO").strip().upper() or "NO REACTIVO",
        "condicion": f.get("condicion", "APTO").strip().upper() or "APTO",
        "emision": emision,
        "vence": (f.get("vence") or "").strip() or mas_un_anio(emision),
        "medico": f.get("medico", "").strip(),
        "foto": foto or "",
    }
    return codigo


@app.route("/c/<codigo>")
def ver_carnet(codigo):
    r = cargar().get(codigo.upper())
    if not r:
        return vista(PAGINA, c=None, previa=False, codigo=""), 404
    vence = datetime.strptime(r["vence"], "%Y-%m-%d").date()
    d = dict(r)
    d.update(dni=r["dni"][:2] + "****" + r["dni"][-2:], emision=fmt(r["emision"]),
             vence=fmt(r["vence"]),
             vigente=r["condicion"] == "APTO" and date.today() <= vence)
    return vista(PAGINA, c=type("C", (), d), previa=bool(session.get("admin")) and not request.args.get("publica"), codigo=codigo.upper())


@app.route("/")
@app.route("/admin")
def admin():
    datos = cargar()
    q = request.args.get("q", "").strip().upper()
    filas = [(k, r) for k, r in sorted(datos.items(), reverse=True)
             if not q or q in (r["apellidos"] + " " + r["nombres"] + " " + r["dni"]).upper()]
    vacio = {k: "" for k in ("apellidos", "nombres", "dni", "grupo", "pulmones", "vdrl",
                             "condicion", "vence", "medico", "foto")}
    vacio["emision"] = date.today().isoformat()
    return vista(ADMIN, filas=filas, total=len(datos), q=q, v=vacio,
                 msg=request.args.get("msg", ""))


@app.route("/nuevo", methods=["POST"])
def nuevo():
    datos = cargar()
    nombre_foto = ""
    foto = request.files.get("foto")
    if foto and foto.filename:
        ext = Path(foto.filename).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            abort(400, "La foto debe ser JPG, PNG o WEBP")
        nombre_foto = f"{secrets.token_hex(8)}{ext}"
        foto.save(FOTOS / nombre_foto)
    codigo = registrar(datos, request.form, nombre_foto)
    guardar(datos)
    return redirect(url_for("ver_carnet", codigo=codigo, previa=1))


@app.route("/editar/<codigo>", methods=["GET", "POST"])
def editar(codigo):
    codigo = codigo.upper()
    datos = cargar()
    r = datos.get(codigo)
    if not r:
        abort(404)
    if request.method == "POST":
        f = request.form
        r.update(
            apellidos=f["apellidos"].strip().upper(), nombres=f["nombres"].strip().upper(),
            dni=f["dni"].strip(), grupo=f.get("grupo", "").strip(),
            pulmones=f.get("pulmones", "NEGATIVO"), vdrl=f.get("vdrl", "NO REACTIVO"),
            condicion=f.get("condicion", "APTO"), emision=f["emision"],
            vence=(f.get("vence") or "").strip() or mas_un_anio(f["emision"]),
            medico=f.get("medico", "").strip())
        foto = request.files.get("foto")
        if foto and foto.filename:
            ext = Path(foto.filename).suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                abort(400, "La foto debe ser JPG, PNG o WEBP")
            if r.get("foto"):
                (FOTOS / r["foto"]).unlink(missing_ok=True)
            r["foto"] = f"{secrets.token_hex(8)}{ext}"
            foto.save(FOTOS / r["foto"])
        guardar(datos)
        return redirect(url_for("ver_carnet", codigo=codigo, previa=1))
    v = {k: r.get(k, "") for k in ("apellidos", "nombres", "dni", "grupo", "pulmones", "vdrl",
                                   "condicion", "emision", "vence", "medico", "foto")}
    return vista(EDITAR, v=v, codigo=codigo)


@app.route("/eliminar/<codigo>", methods=["POST"])
def eliminar(codigo):
    codigo = codigo.upper()
    datos = cargar()
    r = datos.pop(codigo, None)
    if r and r.get("foto"):
        (FOTOS / r["foto"]).unlink(missing_ok=True)
    guardar(datos)
    return redirect(url_for("admin", msg=f"Carnet {codigo} eliminado"))


@app.route("/ajustes", methods=["GET", "POST"])
def ajustes():
    msg = ""
    if request.method == "POST":
        f = request.form
        a = cargar_ajustes()
        a.update(
            entidad=f.get("entidad", "").strip() or ENTIDAD,
            titulo=f.get("titulo", "").strip() or DEFECTO["titulo"],
            pie=f.get("pie", "").strip(),
            carnet_entidad=f.get("carnet_entidad", "").strip() or DEFECTO["carnet_entidad"],
            marca_opacidad=max(0, min(40, int(f.get("marca_opacidad", 12)))),
            marca_tamano=max(20, min(150, int(f.get("marca_tamano", 70)))),
            marca_posicion=max(0, min(100, int(f.get("marca_posicion", 50)))),
            marca_carnet="marca_carnet" in f)
        logo_nuevo = request.files.get("logo")
        if logo_nuevo and logo_nuevo.filename:
            from PIL import Image
            Image.open(logo_nuevo.stream).convert("RGBA").save(LOGO, "PNG")
        firma_nueva = request.files.get("firma")
        if firma_nueva and firma_nueva.filename:
            from PIL import Image
            Image.open(firma_nueva.stream).convert("RGBA").save(FIRMA, "PNG")
        with open(AJUSTES_ARCHIVO, "w", encoding="utf-8") as fh:
            json.dump(a, fh, ensure_ascii=False, indent=2)
        msg = "Ajustes guardados"
    return vista(AJUSTES, msg=msg, firma=FIRMA.exists(), ver=int(LOGO.stat().st_mtime) if LOGO.exists() else 0)


@app.route("/importar", methods=["POST"])
def importar():
    archivo = request.files.get("archivo")
    if not archivo:
        return redirect(url_for("admin", msg="No se envió ningún archivo"))
    texto = archivo.read().decode("utf-8-sig")
    muestra = texto[:2000]
    delim = ";" if muestra.count(";") > muestra.count(",") else ","
    datos = cargar()
    n = 0
    for fila in csv.DictReader(io.StringIO(texto), delimiter=delim):
        fila = {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
        if not (fila.get("dni") and fila.get("apellidos") and fila.get("nombres") and fila.get("emision")):
            continue
        registrar(datos, fila)
        n += 1
    guardar(datos)
    return redirect(url_for("admin", msg=f"Se importaron {n} carnets"))


@app.route("/plantilla.csv")
def plantilla():
    cuerpo = ("apellidos,nombres,dni,grupo,pulmones,vdrl,condicion,emision,vence,medico\n"
              "ESPINOZA SOSA,PEDRO ANTONIO,12345678,RH +,NEGATIVO,NO REACTIVO,APTO,2026-11-04,2027-11-10,\n")
    return Response(cuerpo, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=plantilla_carnets.csv"})


@app.route("/carnet/<codigo>")
def carnet(codigo):
    codigo = codigo.upper()
    if codigo not in cargar():
        abort(404)
    ver = int(max(ARCHIVO.stat().st_mtime,
                  AJUSTES_ARCHIVO.stat().st_mtime if AJUSTES_ARCHIVO.exists() else 0))
    return vista(CARNET, codigo=codigo, ver=ver)


@app.route("/carnet/<codigo>/imagen.png")
def carnet_png(codigo):
    codigo = codigo.upper()
    _, img = imagen_de(codigo)
    cab = {"Cache-Control": "no-store"}
    if request.args.get("descargar"):
        cab["Content-Disposition"] = f"attachment; filename=carnet_{codigo}.png"
    return Response(png_bytes(img), mimetype="image/png", headers=cab)


@app.route("/carnet/<codigo>/carnet.pdf")
def carnet_pdf(codigo):
    codigo = codigo.upper()
    _, img = imagen_de(codigo)
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150.0)
    return Response(buf.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=carnet_{codigo}.pdf"})


@app.route("/carnets.zip")
def carnets_zip():
    datos, aj = cargar(), cargar_ajustes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for codigo, r in datos.items():
            img = dibujar_carnet(codigo, r, aj, f"{base_publica()}/c/{codigo}")
            z.writestr(f"carnet_{codigo}_{r['apellidos'].split()[0]}.png", png_bytes(img))
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": "attachment; filename=carnets.zip"})


@app.route("/qr/<codigo>.png")
def qr_png(codigo):
    codigo = codigo.upper()
    if codigo not in cargar():
        abort(404)
    buf = io.BytesIO()
    qrcode.make(f"{base_publica()}/c/{codigo}").save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@app.route("/logo.png")
def logo():
    if not LOGO.exists():
        abort(404)
    return send_from_directory(BASE, "logo.png")


@app.route("/fotos/<nombre>")
def foto(nombre):
    return send_from_directory(FOTOS, nombre)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
