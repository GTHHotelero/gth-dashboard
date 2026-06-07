#!/usr/bin/env python3
"""
GTH Dashboard Generator — Automatización completa
1. Llama a Claude API para leer PDFs de Drive y generar CSV actualizado
2. Genera index.html y ejecutivo.html desde los templates
3. Sube todo a GitHub via API
"""
import os, sys, json, base64, datetime, urllib.request, urllib.error, csv, io, time
from collections import defaultdict

REPO   = "GTHHotelero/gth-dashboard"
BRANCH = "main"

FOLDER_IDS = {
    "HJ Plaza La Ribera":    "1B3B4c69OE4ouLCU0b2CvdpHlz5CpYCsZ",
    "Howard Johnson Cariló": "15xh9xe37h5lFrT03LVlfoXWIbfs41NJu",
    "Soho Park":             "1ZFrp8rMQHltIX81uECZKFhqyMDF4pA3N",
    "HJ Bahia Blanca":       "1AAPKDiSib61wRj-rrzljQx-682F7Rczj",
}

# ── GitHub helpers ────────────────────────────────────────────────
def github_get(path, token):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "GTH-Dashboard"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

def github_put(path, content_bytes, token, sha=None):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json", "User-Agent": "GTH-Dashboard"}
    body = {"message": f"GTH · {datetime.date.today().strftime('%d/%m/%Y')} · auto", "content": base64.b64encode(content_bytes).decode(), "branch": BRANCH}
    if sha: body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            print(f"  ✅ {path}: {resp['commit']['sha'][:8]}", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"  ❌ {path}: {e.code} {e.read().decode()[:300]}", flush=True)
        return False

def get_sha(path, token):
    try:
        _, sha = github_get(path, token)
        return sha
    except:
        return None

# ── Claude API ────────────────────────────────────────────────────
def llamar_claude(prompt, api_key, max_tokens=4096):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": "claude-opus-4-5",
        "max_tokens": max_tokens,
        "tools": [{
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": 1024,
            "display_height_px": 768
        }],
        "messages": [{"role": "user", "content": prompt}]
    }
    # Usar herramientas MCP de Drive via API
    body_mcp = {
        "model": "claude-opus-4-5",
        "max_tokens": max_tokens,
        "mcp_servers": [{
            "type": "url",
            "url": "https://drivemcp.googleapis.com/mcp/v1",
            "name": "google-drive"
        }],
        "messages": [{"role": "user", "content": prompt}]
    }
    data = json.dumps(body_mcp).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def procesar_reportes_con_claude(api_key, fecha_objetivo, csv_existente):
    """Llama a Claude para que lea los PDFs y devuelva las filas nuevas del CSV"""

    prompt = f"""Sos el asistente del dashboard hotelero de GTH.

TAREA: Leer los PDFs del Manager Report K007 del día {fecha_objetivo} de las 4 carpetas de Google Drive y extraer los datos.

CARPETAS DE DRIVE (buscá el PDF que contenga '{fecha_objetivo.replace('/', '.')}' en el nombre):
- HJ Plaza La Ribera: folder ID 1B3B4c69OE4ouLCU0b2CvdpHlz5CpYCsZ
- Howard Johnson Cariló: folder ID 15xh9xe37h5lFrT03LVlfoXWIbfs41NJu  
- Soho Park: folder ID 1ZFrp8rMQHltIX81uECZKFhqyMDF4pA3N
- HJ Bahia Blanca: folder ID 1AAPKDiSib61wRj-rrzljQx-682F7Rczj

Para cada hotel, extraé del PDF:
- DÍA: Ocup%, ADR, RevPAR, Llegadas, Salidas, Revenue sin IVA, Rooms Revenue, AyB Revenue
- DÍA AA (año anterior): los mismos campos de la columna año anterior
- MES: Ocup%, ADR, RevPAR, Llegadas, Revenue sin IVA, Rooms Revenue, AyB Revenue  
- MES AA: los mismos campos de la columna año anterior
- Manager del hotel

Si un hotel no tiene PDF del día {fecha_objetivo}, marcá sin_k007=true (Dia_Ocup=0, Dia_Rev=0).

Respondé ÚNICAMENTE con las filas CSV nuevas en este formato exacto (sin encabezado, sin explicaciones):
Fecha,Hotel,Color,Hab,Manager,Dia_Ocup,Dia_ADR,Dia_RevPAR,Dia_Lleg,Dia_Sal,Dia_Rev,Dia_Rooms,Dia_AyB,Dia_Rev_AA,Dia_Rooms_AA,Dia_AyB_AA,Mes_Ocup,Mes_ADR,Mes_RevPAR,Mes_Lleg,Mes_Rev,Mes_Rooms,Mes_AyB,Mes_Rev_AA,Mes_Rooms_AA,Mes_AyB_AA,AA_Ocup,AA_ADR,AA_RevPAR

Colores y habitaciones:
- HJ Plaza La Ribera: #378ADD, 104 hab
- Howard Johnson Cariló: #1D9E75, 120 hab
- Soho Park: #D85A30, 43 hab
- HJ Bahia Blanca: #8B6914, 79 hab

CSV EXISTENTE (para no duplicar fechas ya procesadas):
{csv_existente[:500]}...
"""

    try:
        resp = llamar_claude(prompt, api_key)
        # Extraer texto de la respuesta
        texto = ""
        for block in resp.get("content", []):
            if block.get("type") == "text":
                texto += block["text"]
        return texto.strip()
    except Exception as e:
        print(f"  Error llamando a Claude API: {e}", flush=True)
        return None

# ── Generar HTMLs ─────────────────────────────────────────────────
def build_dashboard(csv_data, logo_b64):
    def n(v):
        try: return float(v) if v else 0
        except: return 0

    by_date = defaultdict(dict)
    HOTELES_SET = ["HJ Plaza La Ribera","Howard Johnson Caril\u00f3","Soho Park","HJ Bahia Blanca"]
    HOTEL_COLORS = {"HJ Plaza La Ribera":"#378ADD","Howard Johnson Caril\u00f3":"#1D9E75","Soho Park":"#D85A30","HJ Bahia Blanca":"#8B6914"}
    HOTEL_HAB = {"HJ Plaza La Ribera":104,"Howard Johnson Caril\u00f3":120,"Soho Park":43,"HJ Bahia Blanca":79}

    for r in csv.DictReader(io.StringIO(csv_data.strip())):
        f, h = r['Fecha'], r['Hotel']
        by_date[f][h] = {
            "hotel":h,"color":r['Color'],"hab":int(n(r['Hab'])),"manager":r['Manager'],
            "d_ocup":n(r['Dia_Ocup']),"d_adr":n(r['Dia_ADR']),"d_revpar":n(r['Dia_RevPAR']),
            "d_lleg":int(n(r['Dia_Lleg'])),"d_sal":int(n(r['Dia_Sal'])),
            "d_rev":n(r['Dia_Rev']),"d_rooms":n(r['Dia_Rooms']),"d_ayb":n(r['Dia_AyB']),
            "d_rev_aa":n(r['Dia_Rev_AA']),"d_rooms_aa":n(r['Dia_Rooms_AA']),"d_ayb_aa":n(r['Dia_AyB_AA']),
            "m_ocup":n(r['Mes_Ocup']),"m_adr":n(r['Mes_ADR']),"m_revpar":n(r['Mes_RevPAR']),
            "m_lleg":int(n(r['Mes_Lleg'])),"m_rev":n(r['Mes_Rev']),
            "m_rooms":n(r['Mes_Rooms']),"m_ayb":n(r['Mes_AyB']),
            "m_rev_aa":n(r['Mes_Rev_AA']),"m_rooms_aa":n(r['Mes_Rooms_AA']),"m_ayb_aa":n(r['Mes_AyB_AA']),
            "aa_ocup":n(r['AA_Ocup']),"aa_adr":n(r['AA_ADR']),"aa_revpar":n(r['AA_RevPAR']),
            "sin_k007": n(r['Dia_Ocup'])==0 and n(r['Dia_Rev'])==0 and n(r['Mes_Rev'])>0
        }

    fechas = sorted(by_date.keys(), key=lambda d:[int(x) for x in d.split('/')[::-1]], reverse=True)
    DB_JSON      = json.dumps({f:by_date[f] for f in fechas}, ensure_ascii=False)
    FECHAS_JSON  = json.dumps(fechas)
    HOTELES_JSON = json.dumps([{"nombre":h,"color":HOTEL_COLORS[h],"hab":HOTEL_HAB[h]} for h in HOTELES_SET], ensure_ascii=False)

    with open("template_dashboard.html", encoding="utf-8") as f_t:
        html = f_t.read()

    def replace_const(html, name, value):
        start = html.find(f'const {name} = ')
        end = html.find(';\n', start) + 2
        return html[:start] + f'const {name} = {value};\n' + html[end:]

    html = replace_const(html, 'DB', DB_JSON)
    html = replace_const(html, 'FECHAS', FECHAS_JSON)
    html = replace_const(html, 'HOTELES', HOTELES_JSON)
    return html

def build_ejecutivo(csv_data, logo_b64):
    with open("template_ejecutivo.html", encoding="utf-8") as f_t:
        return f_t.read()

# ── MAIN ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== GTH Dashboard Generator ===", flush=True)

    gh_token    = os.environ.get("GH_TOKEN", "")
    api_key     = os.environ.get("ANTHROPIC_API_KEY", "")
    logo_b64    = os.environ.get("LOGO_B64", "")

    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)
    print(f"API Key: {'OK' if api_key else 'FALTA'}", flush=True)

    # Fecha objetivo: hoy - 1
    ayer = datetime.date.today() - datetime.timedelta(days=1)
    fecha_str = ayer.strftime("%d/%m/%Y")
    print(f"Procesando fecha: {fecha_str}", flush=True)

    # Leer CSV existente
    print("Leyendo datos.csv desde GitHub...", flush=True)
    try:
        csv_data, csv_sha = github_get("datos.csv", gh_token)
        print(f"CSV existente: {len(csv_data.strip().split(chr(10)))-1} registros", flush=True)
    except Exception as e:
        print(f"Error leyendo datos.csv: {e}", flush=True)
        sys.exit(1)

    # Verificar si ya tenemos datos de ayer
    fecha_fmt = ayer.strftime("%d/%m/%Y")
    if fecha_fmt in csv_data:
        print(f"Fecha {fecha_fmt} ya existe en CSV — regenerando HTMLs con datos actuales", flush=True)
    else:
        # Llamar a Claude para procesar los PDFs
        print(f"Llamando a Claude API para procesar PDFs del {fecha_fmt}...", flush=True)
        filas_nuevas = procesar_reportes_con_claude(api_key, fecha_fmt, csv_data)

        if filas_nuevas and len(filas_nuevas) > 10:
            print(f"Claude devolvió {len(filas_nuevas.split(chr(10)))} filas nuevas", flush=True)
            # Agregar filas nuevas al CSV
            header = csv_data.strip().split('\n')[0]
            csv_data = header + '\n' + filas_nuevas + '\n' + '\n'.join(csv_data.strip().split('\n')[1:])
            # Subir CSV actualizado
            print("Subiendo datos.csv actualizado...", flush=True)
            github_put("datos.csv", csv_data.encode("utf-8"), gh_token, sha=csv_sha)
        else:
            print("Claude no devolvió datos válidos — usando CSV existente", flush=True)

    # Generar HTMLs
    print("Generando HTMLs...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars", flush=True)
    print(f"Ejecutivo: {len(html_ejec):,} chars", flush=True)

    # Subir HTMLs
    print("Subiendo HTMLs a GitHub...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))

    print("=== DONE ===", flush=True)
