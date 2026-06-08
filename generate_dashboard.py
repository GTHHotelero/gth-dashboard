#!/usr/bin/env python3
"""
GTH Dashboard Generator — Automatización completa
1. Lee PDFs de Drive via Service Account
2. Envía texto a Claude API para extraer datos
3. Actualiza datos.csv
4. Genera y publica index.html + ejecutivo.html
"""
import os, sys, json, base64, datetime, urllib.request, urllib.error, csv, io, time
from collections import defaultdict

REPO   = "GTHHotelero/gth-dashboard"
BRANCH = "main"

CARPETAS = {
    "HJ Plaza La Ribera":    "1B3B4c69OE4ouLCU0b2CvdpHlz5CpYCsZ",
    "Howard Johnson Caril\u00f3": "15xh9xe37h5lFrT03LVlfoXWIbfs41NJu",
    "Soho Park":             "1ZFrp8rMQHltIX81uECZKFhqyMDF4pA3N",
    "HJ Bahia Blanca":       "1AAPKDiSib61wRj-rrzljQx-682F7Rczj",
}

HOTEL_INFO = {
    "HJ Plaza La Ribera":    {"color":"#378ADD","hab":104},
    "Howard Johnson Caril\u00f3": {"color":"#1D9E75","hab":120},
    "Soho Park":             {"color":"#D85A30","hab":43},
    "HJ Bahia Blanca":       {"color":"#8B6914","hab":79},
}

# ── GitHub ────────────────────────────────────────────────────────
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
        print(f"  ❌ {path}: {e.code} {e.read().decode()[:200]}", flush=True)
        return False

def get_sha(path, token):
    try:
        _, sha = github_get(path, token)
        return sha
    except:
        return None

# ── Google Drive ──────────────────────────────────────────────────
def get_drive_service(sa_json):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)

def buscar_pdf(service, folder_id, fecha):
    """Busca el PDF de la fecha en la carpeta. fecha en formato YYYY.MM.DD"""
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and name contains '{fecha}'"
    result = service.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
    files = result.get("files", [])
    if files:
        # Ordenar por nombre descendente para tomar el más reciente
        files.sort(key=lambda x: x["name"], reverse=True)
        return files[0]
    return None

def exportar_pdf_como_texto(service, file_id):
    """Exporta el PDF como texto usando Drive export"""
    try:
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="ignore")
        return str(content)
    except Exception:
        # Si no funciona export, intentar get_media
        try:
            import io as _io
            from googleapiclient.http import MediaIoBaseDownload
            request = service.files().get_media(fileId=file_id)
            buf = _io.BytesIO()
            dl = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = dl.next_chunk()
            return buf.getvalue().decode("utf-8", errors="ignore")
        except Exception as e2:
            return f"ERROR: {e2}"

# ── Claude API ────────────────────────────────────────────────────
def claude_extraer_datos(api_key, hotel, fecha_display, texto_pdf):
    """Le pasa el texto del PDF a Claude y pide los datos en formato CSV"""
    
    prompt = f"""Sos el asistente del dashboard hotelero GTH. 
Extraé los datos del siguiente reporte K007 del hotel {hotel} del día {fecha_display}.

TEXTO DEL PDF:
{texto_pdf[:8000]}

Respondé ÚNICAMENTE con una línea CSV con exactamente estos campos en este orden (sin encabezado, sin explicaciones, sin texto extra):
Fecha,Hotel,Color,Hab,Manager,Dia_Ocup,Dia_ADR,Dia_RevPAR,Dia_Lleg,Dia_Sal,Dia_Rev,Dia_Rooms,Dia_AyB,Dia_Rev_AA,Dia_Rooms_AA,Dia_AyB_AA,Mes_Ocup,Mes_ADR,Mes_RevPAR,Mes_Lleg,Mes_Rev,Mes_Rooms,Mes_AyB,Mes_Rev_AA,Mes_Rooms_AA,Mes_AyB_AA,AA_Ocup,AA_ADR,AA_RevPAR

Reglas:
- Fecha: {fecha_display}
- Hotel: {hotel}
- Color: {HOTEL_INFO[hotel]['color']}
- Hab: {HOTEL_INFO[hotel]['hab']}
- Manager: nombre del manager que aparece en el reporte
- Dia_Ocup: ocupación del día en % (número sin el símbolo %, ej: 36.89)
- Dia_ADR: tarifa promedio del día SIN IVA en pesos (número entero)
- Dia_RevPAR: revpar del día SIN IVA en pesos (número entero)
- Dia_Lleg: llegadas del día (entero)
- Dia_Sal: salidas del día (entero)
- Dia_Rev: revenue total del día SIN IVA (número entero)
- Dia_Rooms: revenue habitaciones del día SIN IVA (número entero)
- Dia_AyB: revenue alimentos y bebidas del día SIN IVA (número entero)
- Dia_Rev_AA, Dia_Rooms_AA, Dia_AyB_AA: mismos campos pero del año anterior
- Mes_Ocup: ocupación acumulada del mes en % (número sin %)
- Mes_ADR, Mes_RevPAR: acumulado del mes SIN IVA
- Mes_Lleg: llegadas acumuladas del mes
- Mes_Rev, Mes_Rooms, Mes_AyB: revenue acumulado del mes SIN IVA
- Mes_Rev_AA, Mes_Rooms_AA, Mes_AyB_AA: mismos campos año anterior
- AA_Ocup, AA_ADR, AA_RevPAR: datos del año anterior para comparativo
- Si un valor no está disponible usar 0

Ejemplo de formato esperado (solo UNA línea):
{fecha_display},{hotel},{HOTEL_INFO[hotel]['color']},{HOTEL_INFO[hotel]['hab']},Nombre Manager,36.89,137874,50866,28,23,12913750,5239216,6344802,6885295,4749781,1990745,30.29,129176,39129,95,33996139,20151397,12004884,28484667,18375694,9464711,59.41,79163,47028"""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    body = {
        "model": "claude-haiku-4-5",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            texto = resp["content"][0]["text"].strip()
            # Tomar solo la primera línea que tenga comas (la línea CSV)
            for linea in texto.split('\n'):
                linea = linea.strip()
                if linea.count(',') >= 20:
                    return linea
            return None
    except urllib.error.HTTPError as e:
        print(f"    Error Claude API: {e.code} {e.read().decode()[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"    Error: {e}", flush=True)
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

    gh_token  = os.environ.get("GH_TOKEN", "")
    api_key   = os.environ.get("ANTHROPIC_API_KEY", "")
    logo_b64  = os.environ.get("LOGO_B64", "")
    sa_json   = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")

    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)
    print(f"API Key: {'OK' if api_key else 'FALTA'}", flush=True)
    print(f"Drive SA: {'OK' if sa_json else 'FALTA'}", flush=True)

    # Fecha hoy-1
    ayer = datetime.date.today() - datetime.timedelta(days=1)
    fecha_str  = ayer.strftime("%d/%m/%Y")   # 06/06/2026
    fecha_drive = ayer.strftime("%Y.%m.%d")  # 2026.06.06
    print(f"Procesando fecha: {fecha_str}", flush=True)

    # Leer CSV existente
    print("Leyendo datos.csv desde GitHub...", flush=True)
    try:
        csv_data, csv_sha = github_get("datos.csv", gh_token)
        registros = len(csv_data.strip().split('\n')) - 1
        print(f"CSV existente: {registros} registros", flush=True)
    except Exception as e:
        print(f"Error leyendo datos.csv: {e}", flush=True)
        sys.exit(1)

    # Si ya tenemos la fecha, saltar procesamiento
    if fecha_str in csv_data:
        print(f"Fecha {fecha_str} ya existe — regenerando HTMLs", flush=True)
    elif not sa_json or not api_key:
        print(f"Faltan credenciales para procesar PDFs — usando CSV existente", flush=True)
    else:
        # Instalar dependencias de Drive
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                       "google-auth", "google-auth-httplib2", "google-api-python-client"], check=True)

        print(f"Conectando a Google Drive...", flush=True)
        service = get_drive_service(sa_json)

        filas_nuevas = []
        header = csv_data.strip().split('\n')[0]

        for hotel, folder_id in CARPETAS.items():
            print(f"  Procesando {hotel}...", flush=True)

            # Buscar PDF
            pdf = buscar_pdf(service, folder_id, fecha_drive)
            if not pdf:
                print(f"    Sin PDF del {fecha_drive} — marcando sin_k007", flush=True)
                # Buscar último PDF para obtener datos del mes
                result = service.files().list(
                    q=f"'{folder_id}' in parents and mimeType='application/pdf'",
                    orderBy="name desc", pageSize=1, fields="files(id,name)"
                ).execute()
                ultimo = result.get("files", [{}])[0]
                if ultimo:
                    texto = exportar_pdf_como_texto(service, ultimo["id"])
                else:
                    texto = ""
                # Para sin_k007 igualmente llamamos a Claude para extraer datos del mes
            else:
                print(f"    Leyendo {pdf['name']}...", flush=True)
                texto = exportar_pdf_como_texto(service, pdf["id"])

            if texto and len(texto) > 100:
                print(f"    Texto extraído: {len(texto)} chars", flush=True)
                fila = claude_extraer_datos(api_key, hotel, fecha_str, texto)
                if fila and fila.count(',') >= 20:
                    print(f"    ✅ Datos extraídos OK", flush=True)
                    filas_nuevas.append(fila)
                else:
                    print(f"    ⚠️ Claude no devolvió datos válidos", flush=True)
            else:
                print(f"    ⚠️ Texto insuficiente del PDF", flush=True)

        if filas_nuevas:
            print(f"\n{len(filas_nuevas)} hoteles procesados — actualizando CSV...", flush=True)
            lineas_existentes = csv_data.strip().split('\n')
            csv_nuevo = header + '\n' + '\n'.join(filas_nuevas) + '\n' + '\n'.join(lineas_existentes[1:])
            github_put("datos.csv", csv_nuevo.encode("utf-8"), gh_token, sha=csv_sha)
            csv_data = csv_nuevo
        else:
            print("Sin datos nuevos — usando CSV existente", flush=True)

    # Generar y publicar HTMLs
    print("\nGenerando HTMLs...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars", flush=True)
    print(f"Ejecutivo: {len(html_ejec):,} chars", flush=True)

    print("Subiendo a GitHub...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))

    print("=== DONE ===", flush=True)
