#!/usr/bin/env python3
"""GTH Dashboard Generator — GitHub Actions"""
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

def github_get(path, token):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "GTH"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

def github_put(path, content_bytes, token, sha=None):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json", "User-Agent": "GTH"}
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
    try: _, sha = github_get(path, token); return sha
    except: return None

def get_drive_service(sa_json):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=["https://www.googleapis.com/auth/drive"])
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
    """Descarga PDF y extrae todo el texto con pdfminer página por página"""
    import io as _io
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    buf = _io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)

    try:
        from pdfminer.high_level import extract_text
        from pdfminer.layout import LAParams
        buf.seek(0)
        # LAParams ajustado para Crystal Reports
        params = LAParams(line_margin=2.0, word_margin=0.3, char_margin=3.0, boxes_flow=None)
        texto = extract_text(buf, laparams=params)
        return texto
    except Exception as e:
        print(f"    pdfminer error: {e}", flush=True)
        buf.seek(0)
        return buf.read().decode("latin-1", errors="ignore")

def nums_de_seccion(texto, seccion):
    """Extrae lista de números de una sección del PDF"""
    # Buscar la sección
    patron = rf'\b{seccion}\b\s*([\s\S]+?)(?:\b(?:Dia|Mes|A[ñn]o|Totales|Manager)\b|$)'
    m = re.search(patron, texto, re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1)
    # Extraer todos los números
    return re.findall(r'\d{1,3}(?:[,.]\d{3})*(?:\.\d+)?', raw)

def limpiar(s):
    """Convierte string de número a int"""
    try:
        return int(float(str(s).replace(',','')))
    except:
        return 0

def limpiar_f(s):
    """Convierte string de número a float"""
    try:
        return float(str(s).replace(',',''))
    except:
        return 0.0

def extraer_fila_k007(texto, hotel, fecha_display):
    info = HOTEL_INFO[hotel]

    # Manager
    manager = "Sin datos"
    for pat in [
        rf'([A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]+ [A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1][a-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1]+)\s*\n\s*(?:HJ|Howard|Soho)',
        r'Manager[:\s]+([A-Za-z\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00c1\u00c9\u00cd\u00d3\u00da\u00d1 ]+)\n',
    ]:
        m = re.search(pat, texto)
        if m:
            manager = m.group(1).strip()
            break

    # Extraer secciones numéricas
    # El PDF tiene columnas: Dia | Mes | Año | Dia AA | Mes AA | Año AA
    # pdfminer los extrae como bloques separados por sección

    def get_sec(label):
        """Extrae números de una sección por su encabezado"""
        pat = rf'(?<!\w){re.escape(label)}(?!\w)\s*\n([\s\S]{{20,500}}?)(?=\n\s*(?:Dia|Mes|A[ñn]o|Totales|Manager|\Z))'
        m = re.search(pat, texto, re.IGNORECASE)
        if not m: return []
        return re.findall(r'\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?', m.group(1))

    # Intentar extraer por bloques de columna
    # En el formato pdfminer, a veces viene todo junto
    # Buscar los números en orden de aparición dentro de cada bloque

    # Parsear todas las secciones
    secs = {}
    for label in ['Dia', 'Mes', 'Año', 'Ano', 'Dia AA', 'Mes AA']:
        nums = get_sec(label)
        if nums:
            secs[label] = nums

    # Si no encontró secciones, intentar extraer todo junto
    if not secs:
        # Buscar el bloque de números después del encabezado
        todos = re.findall(r'\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?', texto)
        if len(todos) > 20:
            # Asumir que vienen en grupos de ~30 por sección
            chunk = len(todos) // max(1, 3)
            secs = {
                'Dia': todos[:chunk],
                'Mes': todos[chunk:chunk*2],
                'Mes AA': todos[chunk*2:chunk*3]
            }

    def g(sec, idx, tipo='int'):
        nums = secs.get(sec, secs.get(sec.replace('ñ','n'), []))
        if idx < len(nums):
            return limpiar_f(nums[idx]) if tipo=='float' else limpiar(nums[idx])
        return 0

    # Estructura del K007 Crystal Reports:
    # idx 0-4: Hab Totales, Fuera Uso, Hab Activas, En Reparación, Disponibles Venta
    # idx 5: Hab Ocupadas
    # idx 6: Hab Disponibles  
    # idx 7: Ocup%
    # idx 8: Disponibles%
    # idx 9: Llegadas
    # idx 10: Salidas
    # [segmentos varios]
    # Luego en otra parte: Tarifa Promedio, RevPAR, Rooms, AyB, Hotel Revenue

    dia_ocup  = g('Dia', 7, 'float')
    dia_lleg  = g('Dia', 9)
    dia_sal   = g('Dia', 10)
    mes_ocup  = g('Mes', 7, 'float')
    mes_lleg  = g('Mes', 9)

    # Para ADR, RevPAR, Revenue — buscar directamente en el texto completo
    def buscar_kpi(patron):
        """Busca patrón y retorna 5 valores numéricos (Dia, Mes, Año, DiaAA, MesAA)"""
        m = re.search(patron + r'([\s\S]{0,200})', texto, re.IGNORECASE)
        if not m: return [0]*5
        nums = re.findall(r'\d{1,3}(?:[,\.]\d{3})+|\d{4,}', m.group(1))
        result = [limpiar(n) for n in nums[:5]]
        while len(result) < 5: result.append(0)
        return result

    # Tarifa Promedio (ADR)
    adr_vals = buscar_kpi(r'Tarifa\s+Promedio')
    # RevPAR
    rp_vals  = buscar_kpi(r'REVPAR')
    # Rooms Revenue
    rooms_vals = buscar_kpi(r'\bRooms\b')
    # AA&BB
    ayb_vals = buscar_kpi(r'AA\s*[&\\]+\s*BB')
    # Hotel Revenue (sin IVA — primera aparición)
    rev_vals = buscar_kpi(r'Hotel\s+Revenue(?!\s+C)')

    dia_adr    = adr_vals[0];  mes_adr    = adr_vals[1];  aa_adr    = adr_vals[3];  mes_adr_aa  = adr_vals[4]
    dia_rp     = rp_vals[0];   mes_rp     = rp_vals[1];   aa_rp     = rp_vals[3];   mes_rp_aa   = rp_vals[4]
    dia_rooms  = rooms_vals[0]; mes_rooms  = rooms_vals[1]; aa_rooms  = rooms_vals[3]; mes_rooms_aa = rooms_vals[4]
    dia_ayb    = ayb_vals[0];  mes_ayb    = ayb_vals[1];  aa_ayb    = ayb_vals[3];  mes_ayb_aa  = ayb_vals[4]
    dia_rev    = rev_vals[0];  mes_rev    = rev_vals[1];  aa_rev    = rev_vals[3];  mes_rev_aa  = rev_vals[4]

    # AA Ocup (año anterior)
    aa_ocup_vals = get_sec('Año') or get_sec('Ano')
    aa_ocup = limpiar_f(aa_ocup_vals[7]) if len(aa_ocup_vals) > 7 else 0.0

    return (
        f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
        f"{dia_ocup},{dia_adr},{dia_rp},{dia_lleg},{dia_sal},"
        f"{dia_rev},{dia_rooms},{dia_ayb},"
        f"{aa_rev},{aa_rooms},{aa_ayb},"
        f"{mes_ocup},{mes_adr},{mes_rp},{mes_lleg},"
        f"{mes_rev},{mes_rooms},{mes_ayb},"
        f"{mes_rev_aa},{mes_rooms_aa},{mes_ayb_aa},"
        f"{aa_ocup},{aa_adr},{aa_rp}"
    )


def claude_completar_datos(api_key, hotel, fecha, texto_pdf, datos_parciales):
    """Usa Claude API para extraer datos del PDF incluso con texto parcial"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    info = HOTEL_INFO[hotel]
    
    prompt = f"""Sos el asistente del dashboard hotelero GTH.
Del texto del Manager Report K007 de {hotel} del {fecha}, extraé los datos numéricos.

TEXTO DEL PDF:
{texto_pdf[:4000]}

Datos que ya pude extraer: {datos_parciales}

Respondé SOLO con una línea CSV con exactamente estos 29 campos (sin encabezado ni texto adicional):
{fecha},{hotel},{info['color']},{info['hab']},[Manager],[Dia_Ocup%],[Dia_ADR],[Dia_RevPAR],[Dia_Llegadas],[Dia_Salidas],[Dia_Revenue],[Dia_Rooms],[Dia_AyB],[Dia_Rev_AA],[Dia_Rooms_AA],[Dia_AyB_AA],[Mes_Ocup%],[Mes_ADR],[Mes_RevPAR],[Mes_Llegadas],[Mes_Revenue],[Mes_Rooms],[Mes_AyB],[Mes_Rev_AA],[Mes_Rooms_AA],[Mes_AyB_AA],[AA_Ocup%],[AA_ADR],[AA_RevPAR]

Reglas:
- Revenue SIN IVA (buscar "Hotel Revenue" sin "C/IVA")
- Ocup% sin el símbolo (ej: 37.21)
- Revenue en pesos enteros (ej: 2500000)
- Columnas del PDF: Dia | Mes | Año | Dia AA | Mes AA | Año AA
- Si un dato no aparece en el texto usar 0
- Manager: nombre que aparece en el reporte"""

    body = {
        "model": "claude-haiku-4-5",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            texto = resp["content"][0]["text"].strip()
            for linea in texto.split("\n"):
                linea = linea.strip()
                if linea.count(",") >= 20:
                    return linea
        return None
    except Exception as e:
        print(f"    Claude API error: {e}", flush=True)
        return None

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
    DB_JSON = json.dumps({f:by_date[f] for f in fechas}, ensure_ascii=False)
    FECHAS_JSON = json.dumps(fechas)
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

if __name__ == "__main__":
    print("=== GTH Dashboard Generator ===", flush=True)
    gh_token = os.environ.get("GH_TOKEN","")
    logo_b64 = os.environ.get("LOGO_B64","")
    sa_json  = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON","")
    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)
    print(f"Drive SA: {'OK' if sa_json else 'FALTA'}", flush=True)

    ayer = datetime.date.today() - datetime.timedelta(days=1)
    fecha_str   = ayer.strftime("%d/%m/%Y")
    fecha_drive = ayer.strftime("%Y.%m.%d")
    print(f"Procesando fecha: {fecha_str}", flush=True)

    print("Leyendo datos.csv...", flush=True)
    try:
        csv_data, csv_sha = github_get("datos.csv", gh_token)
        print(f"CSV: {len(csv_data.strip().split(chr(10)))-1} registros", flush=True)
    except Exception as e:
        print(f"Error: {e}", flush=True); sys.exit(1)

    if fecha_str in csv_data:
        print(f"Fecha {fecha_str} ya existe", flush=True)
    elif not sa_json:
        print("Sin Drive SA", flush=True)
    else:
        import subprocess
        subprocess.run([sys.executable,"-m","pip","install","-q",
            "google-auth","google-auth-httplib2","google-api-python-client","pdfminer.six"], check=True)

        print("Conectando a Drive...", flush=True)
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
            if not texto or len(texto) < 50:
                print(f"    Texto insuficiente ({len(texto) if texto else 0} chars)", flush=True)
                continue
            print(f"    Texto: {len(texto)} chars", flush=True)
            fila = extraer_fila_k007(texto, hotel, fecha_str)
            campos = fila.split(',')
            print(f"    Parser: Ocup={campos[5]}% ADR={campos[6]} Rev={campos[10]}", flush=True)
            
            # Si ADR o Revenue son 0, usar Claude para completar
            api_key = os.environ.get("ANTHROPIC_API_KEY","")
            if api_key and (campos[6] == '0' or campos[10] == '0'):
                print(f"    Completando con Claude API...", flush=True)
                datos_parciales = f"Ocup={campos[5]}%, Llegadas={campos[8]}, Salidas={campos[9]}"
                fila_claude = claude_completar_datos(api_key, hotel, fecha_str, texto, datos_parciales)
                if fila_claude and fila_claude.count(",") >= 20:
                    fila = fila_claude
                    campos = fila.split(",")
                    print(f"    Claude: Ocup={campos[5]}% ADR={campos[6]} Rev={campos[10]}", flush=True)
            
            filas_nuevas.append(fila)

        if filas_nuevas:
            print(f"{len(filas_nuevas)} hoteles OK", flush=True)
            lineas = csv_data.strip().split('\n')
            csv_nuevo = header + '\n' + '\n'.join(filas_nuevas) + '\n' + '\n'.join(lineas[1:])
            github_put("datos.csv", csv_nuevo.encode("utf-8"), gh_token, sha=csv_sha)
            csv_data = csv_nuevo
        else:
            print("Sin datos nuevos", flush=True)

    print("Generando HTMLs...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars | Ejecutivo: {len(html_ejec):,} chars", flush=True)
    print("Subiendo...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))
    print("=== DONE ===", flush=True)
