#!/usr/bin/env python3
"""
GTH Dashboard Generator — GitHub Actions
Lee PDFs de Drive, parsea con Python, publica HTMLs.
Sin dependencia de Claude API para el parseo.
"""
import os, sys, json, base64, datetime, urllib.request, urllib.error, csv, io, re
from collections import defaultdict

REPO   = "GTHHotelero/gth-dashboard"
BRANCH = "main"

CARPETAS = {
    "HJ Plaza La Ribera":         "1B3B4c69OE4ouLCU0b2CvdpHlz5CpYCsZ",
    "Howard Johnson Caril\u00f3": "15xh9xe37h5lFrT03LVlfoXWIbfs41NJu",
    "Soho Park":                  "1ZFrp8rMQHltIX81uECZKFhqyMDF4pA3N",
    "HJ Bahia Blanca":            "1AAPKDiSib61wRj-rrzljQx-682F7Rczj",
}

HOTEL_INFO = {
    "HJ Plaza La Ribera":         {"color":"#378ADD","hab":104},
    "Howard Johnson Caril\u00f3": {"color":"#1D9E75","hab":120},
    "Soho Park":                  {"color":"#D85A30","hab":43},
    "HJ Bahia Blanca":            {"color":"#8B6914","hab":79},
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
    body = {"message": f"GTH \u00b7 {datetime.date.today().strftime('%d/%m/%Y')} \u00b7 auto", "content": base64.b64encode(content_bytes).decode(), "branch": BRANCH}
    if sha: body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            print(f"  \u2705 {path}: {resp['commit']['sha'][:8]}", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"  \u274c {path}: {e.code} {e.read().decode()[:200]}", flush=True)
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
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)

def buscar_pdf(service, folder_id, fecha_drive):
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and name contains '{fecha_drive}'"
    result = service.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
    files = result.get("files", [])
    if files:
        files.sort(key=lambda x: x["name"], reverse=True)
        return files[0]
    return None

def exportar_pdf_texto(service, file_id):
    """Extrae texto del PDF via Google Drive OCR"""
    import io as _io
    from googleapiclient.http import MediaIoBaseDownload
    from googleapiclient.discovery import build as gdrive_build

    # Método 1: Copiar PDF como Google Doc (Drive hace OCR automático)
    try:
        # Crear copia como Google Doc para extraer texto
        file_meta = {"name": "temp_ocr", "mimeType": "application/vnd.google-apps.document"}
        copied = service.files().copy(
            fileId=file_id,
            body=file_meta,
            fields="id"
        ).execute()
        doc_id = copied["id"]
        
        # Exportar el Google Doc como texto plano
        texto_bytes = service.files().export(
            fileId=doc_id,
            mimeType="text/plain"
        ).execute()
        
        # Borrar el doc temporal
        try:
            service.files().delete(fileId=doc_id).execute()
        except:
            pass
        
        if isinstance(texto_bytes, bytes):
            texto = texto_bytes.decode("utf-8", errors="ignore")
        else:
            texto = str(texto_bytes)
        
        print(f"    OCR via Google Doc: {len(texto)} chars", flush=True)
        return texto
        
    except Exception as e1:
        print(f"    OCR falló: {e1} — usando get_media", flush=True)
        
    # Método 2: Descargar PDF y usar pdfminer
    try:
        request = service.files().get_media(fileId=file_id)
        buf = _io.BytesIO()
        dl = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        from pdfminer.high_level import extract_text
        texto = extract_text(buf)
        print(f"    pdfminer: {len(texto)} chars", flush=True)
        return texto
    except Exception as e2:
        print(f"    pdfminer falló: {e2}", flush=True)
        return ""

# ── Parseo del texto del PDF ──────────────────────────────────────
def extraer_numero(texto, patron):
    """Extrae el primer número después del patrón"""
    match = re.search(patron + r'[\s\n]+([0-9,\.]+)', texto, re.IGNORECASE)
    if match:
        return match.group(1).replace(',', '').replace('.', '').strip()
    return '0'

def extraer_fila_k007(texto, hotel, fecha_display):
    """
    Parsea el texto del PDF K007 y extrae los campos necesarios.
    El formato del PDF tiene columnas: Dia | Mes | Año | Dia AA | Mes AA | Año AA
    """
    info = HOTEL_INFO[hotel]

    # Manager — aparece al final del PDF antes del nombre del hotel
    manager = "Sin datos"
    # Buscar nombre antes de "HJ Plaza" o "Soho" etc
    manager_match = re.search(r'([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+ [A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\s*\n\s*(?:HJ|Howard|Soho)', texto)
    if manager_match:
        manager = manager_match.group(1).strip()
    else:
        # Buscar NOMBRE APELLIDO en mayúsculas
        manager_match2 = re.search(r'([A-ZÁÉÍÓÚÑ]{2,} [A-ZÁÉÍÓÚÑ]{2,}(?:\s[A-ZÁÉÍÓÚÑ]{2,})?)\s*\n', texto)
        if manager_match2:
            manager = manager_match2.group(1).title().strip()

    def get_cols(label):
        """Extrae las 6 columnas numéricas de una fila del PDF"""
        # Buscar la línea con el label y extraer todos los números seguidos
        pattern = label + r'[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)'
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            return [int(float(g.replace(',',''))) for g in m.groups()]
        return [0,0,0,0,0,0]

    def get_2cols(label):
        """Extrae solo las 2 primeras columnas"""
        pattern = label + r'[\s\n]+([\d,\.]+)[\s\n]+([\d,\.]+)'
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            return [int(float(g.replace(',',''))) for g in m.groups()]
        return [0,0]

    def get_pct(label):
        """Extrae porcentajes (pueden tener decimales)"""
        pattern = label + r'[\s\n]+([\d]+\.[\d]+)[\s\n]+([\d]+\.[\d]+)[\s\n]+([\d]+\.[\d]+)[\s\n]+([\d]+\.[\d]+)[\s\n]+([\d]+\.[\d]+)'
        m = re.search(pattern, texto, re.IGNORECASE)
        if m:
            return [float(g) for g in m.groups()]
        return [0.0,0.0,0.0,0.0,0.0]

    # Extraer datos
    ocup = get_pct(r'Porcentaje de Ocupaci[oó]n')
    dia_ocup  = ocup[0] if len(ocup)>0 else 0
    mes_ocup  = ocup[1] if len(ocup)>1 else 0
    aa_ocup   = ocup[3] if len(ocup)>3 else 0
    mes_ocup_aa = ocup[4] if len(ocup)>4 else 0

    llegadas = get_cols(r'Cantidad de Llegadas\b')
    dia_lleg = llegadas[0] if llegadas else 0
    mes_lleg = llegadas[1] if llegadas else 0

    salidas = get_cols(r'Cantidad de Salidas\b')
    dia_sal = salidas[0] if salidas else 0

    # Tarifa Promedio (ADR) — columnas: Dia Mes Año DiaAA MesAA AñoAA
    adr_match = re.search(r'Tarifa Promedio[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)', texto)
    if adr_match:
        dia_adr, mes_adr, _, aa_adr, mes_adr_aa = [int(g.replace(',','')) for g in adr_match.groups()]
    else:
        dia_adr = mes_adr = aa_adr = mes_adr_aa = 0

    revpar_match = re.search(r'REVPAR[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)', texto)
    if revpar_match:
        dia_rp, mes_rp, _, aa_rp, mes_rp_aa = [int(g.replace(',','')) for g in revpar_match.groups()]
    else:
        dia_rp = mes_rp = aa_rp = mes_rp_aa = 0

    # Rooms Revenue
    rooms_match = re.search(r'Rooms[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)', texto)
    if rooms_match:
        dia_rooms, mes_rooms, _, aa_rooms, mes_rooms_aa = [int(g.replace(',','')) for g in rooms_match.groups()]
    else:
        dia_rooms = mes_rooms = aa_rooms = mes_rooms_aa = 0

    # AA&BB Revenue
    aabb_match = re.search(r'AA[\\&]+BB[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)', texto)
    if aabb_match:
        dia_ayb, mes_ayb, _, aa_ayb, mes_ayb_aa = [int(g.replace(',','')) for g in aabb_match.groups()]
    else:
        dia_ayb = mes_ayb = aa_ayb = mes_ayb_aa = 0

    # Hotel Revenue (sin IVA)
    rev_match = re.search(r'Hotel Revenue[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)[\s\n]+([\d,]+)', texto)
    if rev_match:
        dia_rev, mes_rev, _, aa_rev, mes_rev_aa = [int(g.replace(',','')) for g in rev_match.groups()]
    else:
        dia_rev = mes_rev = aa_rev = mes_rev_aa = 0

    fila = (
        f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
        f"{dia_ocup},{dia_adr},{dia_rp},{dia_lleg},{dia_sal},"
        f"{dia_rev},{dia_rooms},{dia_ayb},"
        f"{aa_rev},{aa_rooms},{aa_ayb},"
        f"{mes_ocup},{mes_adr},{mes_rp},{mes_lleg},"
        f"{mes_rev},{mes_rooms},{mes_ayb},"
        f"{mes_rev_aa},{mes_rooms_aa},{mes_ayb_aa},"
        f"{aa_ocup},{aa_adr},{aa_rp}"
    )
    return fila

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
    logo_b64  = os.environ.get("LOGO_B64", "")
    sa_json   = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")

    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)
    print(f"Drive SA: {'OK' if sa_json else 'FALTA'}", flush=True)

    ayer = datetime.date.today() - datetime.timedelta(days=1)
    fecha_str   = ayer.strftime("%d/%m/%Y")
    fecha_drive = ayer.strftime("%Y.%m.%d")
    print(f"Procesando fecha: {fecha_str}", flush=True)

    print("Leyendo datos.csv desde GitHub...", flush=True)
    try:
        csv_data, csv_sha = github_get("datos.csv", gh_token)
        print(f"CSV: {len(csv_data.strip().split(chr(10)))-1} registros", flush=True)
    except Exception as e:
        print(f"Error: {e}", flush=True)
        sys.exit(1)

    if fecha_str in csv_data:
        print(f"Fecha {fecha_str} ya existe — regenerando HTMLs", flush=True)
    elif not sa_json:
        print("Sin Drive SA — usando CSV existente", flush=True)
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
            "google-auth", "google-auth-httplib2", "google-api-python-client", "pdfminer.six"], check=True)

        print("Conectando a Google Drive...", flush=True)
        service = get_drive_service(sa_json)

        filas_nuevas = []
        header = csv_data.strip().split('\n')[0]

        for hotel, folder_id in CARPETAS.items():
            print(f"  {hotel}...", flush=True)
            pdf = buscar_pdf(service, folder_id, fecha_drive)

            if not pdf:
                print(f"    Sin PDF del {fecha_drive}", flush=True)
                continue

            print(f"    Leyendo {pdf['name']}...", flush=True)
            texto = exportar_pdf_texto(service, pdf["id"])

            if not texto or len(texto) < 100:
                print(f"    Texto insuficiente", flush=True)
                continue

            print(f"    Texto: {len(texto)} chars — parseando...", flush=True)
            print(f"    Muestra: {repr(texto[:300])}", flush=True)
            fila = extraer_fila_k007(texto, hotel, fecha_str)
            campos = fila.split(',')
            print(f"    Ocup: {campos[5]}% | ADR: {campos[6]} | Rev: {campos[10]}", flush=True)
            filas_nuevas.append(fila)

        if filas_nuevas:
            print(f"\n{len(filas_nuevas)} hoteles procesados", flush=True)
            lineas = csv_data.strip().split('\n')
            csv_nuevo = header + '\n' + '\n'.join(filas_nuevas) + '\n' + '\n'.join(lineas[1:])
            github_put("datos.csv", csv_nuevo.encode("utf-8"), gh_token, sha=csv_sha)
            csv_data = csv_nuevo
        else:
            print("Sin datos nuevos", flush=True)

    print("\nGenerando HTMLs...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars", flush=True)
    print(f"Ejecutivo: {len(html_ejec):,} chars", flush=True)

    print("Subiendo a GitHub...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))

    print("=== DONE ===", flush=True)
