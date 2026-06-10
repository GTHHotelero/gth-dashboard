#!/usr/bin/env python3
"""GTH Dashboard Generator — GitHub Actions"""
import os, sys, json, base64, datetime, urllib.request, urllib.error, csv, io, re
from collections import defaultdict

REPO   = "GTHHotelero/gth-dashboard"
BRANCH = "main"

CARPETAS = {
    "HJ Plaza La Ribera":         "1B3B4c69OE4ouLCU0b2CvdpHlz5CpYCsZ",
    "Howard Johnson Cariló":      "15xh9xe37h5lFrT03LVlfoXWIbfs41NJu",
    "Soho Park":                  "1ZFrp8rMQHltIX81uECZKFhqyMDF4pA3N",
    "HJ Bahia Blanca":            "1AAPKDiSib61wRj-rrzljQx-682F7Rczj",
}
HOTEL_INFO = {
    "HJ Plaza La Ribera":         {"color":"#378ADD","hab":104},
    "Howard Johnson Cariló":      {"color":"#1D9E75","hab":120},
    "Soho Park":                  {"color":"#D85A30","hab":43},
    "HJ Bahia Blanca":            {"color":"#8B6914","hab":79},
}

CSV_HEADER = (
    "Fecha,Hotel,Color,Hab,Manager,"
    "Dia_Ocup,Dia_ADR,Dia_RevPAR,Dia_Lleg,Dia_Sal,"
    "Dia_Rev,Dia_Rooms,Dia_AyB,"
    "Dia_Rev_AA,Dia_Rooms_AA,Dia_AyB_AA,"
    "Mes_Ocup,Mes_ADR,Mes_RevPAR,Mes_Lleg,"
    "Mes_Rev,Mes_Rooms,Mes_AyB,"
    "Mes_Rev_AA,Mes_Rooms_AA,Mes_AyB_AA,"
    "AA_Ocup,AA_ADR,AA_RevPAR,"
    "Dia_Hab_Ocup,Dia_House_Use,Dia_Ocup_GTH"
)

# ── GitHub helpers ────────────────────────────────────────────────────────────

def github_get(path, token):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "GTH"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

def github_put(path, content_bytes, token, sha=None):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json",
               "Content-Type": "application/json", "User-Agent": "GTH"}
    body = {"message": f"GTH · {datetime.date.today().strftime('%d/%m/%Y')} · auto",
            "content": base64.b64encode(content_bytes).decode(), "branch": BRANCH}
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
    try: _, sha = github_get(path, token); return sha
    except: return None

# ── Drive helpers ─────────────────────────────────────────────────────────────

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
        params = LAParams(line_margin=2.0, word_margin=0.3, char_margin=3.0, boxes_flow=None)
        return extract_text(buf, laparams=params)
    except Exception as e:
        print(f"    pdfminer error: {e}", flush=True)
        buf.seek(0)
        return buf.read().decode("latin-1", errors="ignore")

# ── Parsers ───────────────────────────────────────────────────────────────────

def es_formato_bba(texto):
    """BBA: pdfminer pone los números ANTES de los labels"""
    return bool(re.search(r'[\d\.]+\nPorcentaje de Ocupaci', texto))

def extraer_hab_house_normal(texto):
    """
    Formato normal (PLR, Cariló, Soho):
      'Habitaciones Ocupadas 24 287 6,889 ...'  → primer número = Dia
      'House Use 1 10 107 ...'                   → primer número = Dia
    """
    hab_ocup = 0
    house_use = 0
    m = re.search(r'Habitaciones Ocupadas\s+([\d,]+)', texto)
    if m:
        hab_ocup = int(m.group(1).replace(',', ''))
    m = re.search(r'House Use\s+([\d,]+)', texto)
    if m:
        house_use = int(m.group(1).replace(',', ''))
    return hab_ocup, house_use

def extraer_hab_house_bba(texto):
    """
    Formato BBA (número ANTES del label):
      '44\nHabitaciones Ocupadas'
      '9\nHouse Use'
    """
    hab_ocup = 0
    house_use = 0
    m = re.search(r'([\d,]+)\nHabitaciones Ocupadas', texto)
    if m:
        hab_ocup = int(m.group(1).replace(',', ''))
    m = re.search(r'([\d,]+)\nHouse Use', texto)
    if m:
        house_use = int(m.group(1).replace(',', ''))
    return hab_ocup, house_use

def calcular_ocup_gth(hab_ocup, house_use, hab_total):
    """Ocupación GTH = (Hab Ocupadas - House Use) / Hab Totales * 100"""
    if hab_total <= 0 or hab_ocup <= 0:
        return 0.0
    return round(max(0, hab_ocup - house_use) / hab_total * 100, 2)

def get_sec(texto, label, terminators):
    le = re.escape(label)
    pat = rf'\b{le}\b\s*\n([\s\S]+?)(?=\n\s*(?:{terminators}|\Z))'
    m = re.search(pat, texto)
    if not m: return []
    return re.findall(r'[\d,]+\.?\d*', m.group(1))

def ni(lst, idx):
    try: return int(float(str(lst[idx]).replace(',', '')))
    except: return 0

def nf(lst, idx):
    try: return float(str(lst[idx]).replace(',', ''))
    except: return 0.0

def find_adr_idx(nums):
    for i in range(20, len(nums)):
        try:
            v = float(str(nums[i]).replace(',', ''))
            if 50000 <= v <= 600000: return i
        except: pass
    return 32

def extraer_manager_normal(texto):
    pat = re.compile(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,15}(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,15}){1,2}$')
    lineas = texto.strip().split("\n")
    for linea in lineas[:5]:
        if pat.match(linea.strip()): return linea.strip()
    for linea in reversed(lineas):
        if pat.match(linea.strip()): return linea.strip()
    return "Sin datos"

def extraer_fila_normal(texto, hotel, fecha_display):
    """Parser para PLR, Cariló, Soho — columnas: Dia | Mes | Año | Dia AA | Mes AA"""
    info = HOTEL_INFO[hotel]
    manager = extraer_manager_normal(texto)

    NEXT_DIA   = r'Mes\b|Año\b|DiaAA\b|Dia AA|Habitaciones'
    NEXT_MES   = r'Año\b|DiaAA\b|MesAA\b|Dia AA|Mes AA|Habitaciones'
    NEXT_DIAAA = r'MesAA\b|Mes AA|AñoA\b|Año A|Habitaciones'
    NEXT_MESAA = r'AñoA\b|Año A|Habitaciones'

    dia    = get_sec(texto, 'Dia',   NEXT_DIA)
    mes    = get_sec(texto, 'Mes',   NEXT_MES)
    dia_aa = get_sec(texto, 'DiaAA', NEXT_DIAAA) or get_sec(texto, 'Dia AA', NEXT_DIAAA)
    mes_aa = get_sec(texto, 'MesAA', NEXT_MESAA) or get_sec(texto, 'Mes AA', NEXT_MESAA)

    tiene_tot_hab = 'TOTAL REVENUE / HAB' in texto.upper()
    rooms_off = 4 if tiene_tot_hab else 3
    ayb_off   = 5 if tiene_tot_hab else 4

    def get_kpis(sec):
        if not sec: return {'adr':0,'rp':0,'rooms':0,'ayb':0,'rev':0}
        s = find_adr_idx(sec)
        return {'adr': ni(sec,s), 'rp': ni(sec,s+1),
                'rooms': ni(sec,s+rooms_off), 'ayb': ni(sec,s+ayb_off),
                'rev': ni(sec,-2) if len(sec)>=2 else 0}

    d   = get_kpis(dia)
    m   = get_kpis(mes)
    aa  = get_kpis(dia_aa)
    maa = get_kpis(mes_aa)

    dia_ocup = nf(dia, 7); dia_lleg = ni(dia, 9); dia_sal = ni(dia, 10)
    mes_ocup = nf(mes, 7); mes_lleg = ni(mes, 9)
    aa_ocup  = nf(dia_aa, 7) if dia_aa else 0.0

    # Ocupación GTH
    hab_ocup, house_use = extraer_hab_house_normal(texto)
    ocup_gth = calcular_ocup_gth(hab_ocup, house_use, info['hab'])
    print(f"    GTH Ocup: ({hab_ocup} - {house_use}) / {info['hab']} = {ocup_gth}%", flush=True)

    return (
        f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
        f"{dia_ocup},{d['adr']},{d['rp']},{dia_lleg},{dia_sal},"
        f"{d['rev']},{d['rooms']},{d['ayb']},"
        f"{aa['rev']},{aa['rooms']},{aa['ayb']},"
        f"{mes_ocup},{m['adr']},{m['rp']},{mes_lleg},"
        f"{m['rev']},{m['rooms']},{m['ayb']},"
        f"{maa['rev']},{maa['rooms']},{maa['ayb']},"
        f"{aa_ocup},{aa['adr']},{aa['rp']},"
        f"{hab_ocup},{house_use},{ocup_gth}"
    )

def extraer_fila_bba(texto, hotel, fecha_display):
    """Parser para BBA — números antes de labels"""
    info = HOTEL_INFO[hotel]

    manager = "Sin datos"
    mgr_m = re.match(r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})\s*\n', texto.strip())
    if mgr_m:
        manager = mgr_m.group(1)

    def vbl(label):
        m = re.search(r'([\d,\.]+)\n' + re.escape(label), texto)
        return float(m.group(1).replace(',', '')) if m else 0.0

    def vbl_int(label):
        return int(vbl(label))

    NEXT_MES = r'Año\b|DiaAA\b|MesAA\b|AñoA\b|Habitaciones'
    mes_sec = get_sec(texto, 'Mes', NEXT_MES)

    dia_ocup  = vbl('Porcentaje de Ocupación')
    dia_lleg  = vbl_int('Cantidad de Llegadas')
    dia_sal   = vbl_int('Cantidad de Salidas')
    dia_adr   = vbl_int('Tarifa Promedio')
    dia_rooms = vbl_int('Rooms')

    dia_ayb_m = re.search(r'([\d,]+)\nAA[&\\]+BB', texto)
    dia_ayb   = int(float(dia_ayb_m.group(1).replace(',', ''))) if dia_ayb_m else 0
    dia_rev_m = re.search(r'([\d,]+)\nHotel Revenue\n', texto)
    dia_rev   = int(float(dia_rev_m.group(1).replace(',', ''))) if dia_rev_m else 0
    rp_m      = re.search(r'REVPAR\n([\d,]+)', texto)
    dia_rp    = int(float(rp_m.group(1).replace(',', ''))) if rp_m else 0

    if mes_sec and len(mes_sec) > 35:
        s = find_adr_idx(mes_sec)
        mes_ocup  = nf(mes_sec, 7)
        mes_lleg  = ni(mes_sec, 9)
        mes_adr   = ni(mes_sec, s)
        mes_rp    = ni(mes_sec, s+1)
        mes_rooms = ni(mes_sec, s+4)
        mes_ayb   = ni(mes_sec, s+5)
        mes_rev   = ni(mes_sec, -2) if len(mes_sec)>=2 else 0
    else:
        mes_ocup = mes_lleg = mes_adr = mes_rp = mes_rooms = mes_ayb = mes_rev = 0

    # Ocupación GTH
    hab_ocup, house_use = extraer_hab_house_bba(texto)
    ocup_gth = calcular_ocup_gth(hab_ocup, house_use, info['hab'])
    print(f"    GTH Ocup BBA: ({hab_ocup} - {house_use}) / {info['hab']} = {ocup_gth}%", flush=True)

    return (
        f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
        f"{dia_ocup},{dia_adr},{dia_rp},{dia_lleg},{dia_sal},"
        f"{dia_rev},{dia_rooms},{dia_ayb},"
        f"0,0,0,"
        f"{mes_ocup},{mes_adr},{mes_rp},{mes_lleg},"
        f"{mes_rev},{mes_rooms},{mes_ayb},"
        f"0,0,0,"
        f"0.0,0,0,"
        f"{hab_ocup},{house_use},{ocup_gth}"
    )

def extraer_fila_k007(texto, hotel, fecha_display):
    if hotel == "HJ Bahia Blanca" or es_formato_bba(texto):
        return extraer_fila_bba(texto, hotel, fecha_display)
    return extraer_fila_normal(texto, hotel, fecha_display)

# ── Claude fallback ───────────────────────────────────────────────────────────

def claude_completar_datos(api_key, hotel, fecha, texto_pdf, datos_parciales):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    info = HOTEL_INFO[hotel]
    prompt = f"""Sos el asistente del dashboard hotelero GTH.
Del texto del Manager Report K007 de {hotel} del {fecha}, extraé los datos numéricos.

TEXTO DEL PDF:
{texto_pdf[:4000]}

Datos que ya pude extraer: {datos_parciales}

Respondé SOLO con una línea CSV con exactamente estos 32 campos (sin encabezado):
{fecha},{hotel},{info['color']},{info['hab']},[Manager],[Dia_Ocup%],[Dia_ADR],[Dia_RevPAR],[Dia_Llegadas],[Dia_Salidas],[Dia_Revenue],[Dia_Rooms],[Dia_AyB],[Dia_Rev_AA],[Dia_Rooms_AA],[Dia_AyB_AA],[Mes_Ocup%],[Mes_ADR],[Mes_RevPAR],[Mes_Llegadas],[Mes_Revenue],[Mes_Rooms],[Mes_AyB],[Mes_Rev_AA],[Mes_Rooms_AA],[Mes_AyB_AA],[AA_Ocup%],[AA_ADR],[AA_RevPAR],[Dia_Hab_Ocup],[Dia_House_Use],[Dia_Ocup_GTH]

Reglas:
- Revenue SIN IVA
- Ocup% sin símbolo (ej: 37.21)
- Dia_Ocup_GTH = (Dia_Hab_Ocup - Dia_House_Use) / Hab_Totales_Hotel * 100
- Si un dato no aparece usar 0"""

    body = {"model": "claude-haiku-4-5", "max_tokens": 600,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            texto = resp["content"][0]["text"].strip()
            for linea in texto.split("\n"):
                linea = linea.strip()
                if linea.count(",") >= 31:
                    return linea
        return None
    except Exception as e:
        print(f"    Claude API error: {e}", flush=True)
        return None

# ── CSV helpers ───────────────────────────────────────────────────────────────

def normalizar_csv(csv_data):
    """
    Asegura que todas las filas tengan las columnas nuevas.
    Filas viejas sin Dia_Hab_Ocup/Dia_House_Use/Dia_Ocup_GTH → agrega 0,0,0
    También actualiza el header si es viejo.
    """
    lineas = csv_data.strip().split('\n')
    header_viejo = lineas[0]
    campos_header = header_viejo.split(',')

    # Si ya tiene el header nuevo, no tocar
    if 'Dia_Ocup_GTH' in header_viejo:
        return csv_data

    # Header nuevo
    nuevo_header = CSV_HEADER
    n_campos_nuevo = len(nuevo_header.split(','))
    n_campos_viejo = len(campos_header)

    nuevas_lineas = [nuevo_header]
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        campos = linea.split(',')
        # Completar con 0s si faltan columnas
        while len(campos) < n_campos_nuevo:
            campos.append('0')
        nuevas_lineas.append(','.join(campos[:n_campos_nuevo]))

    return '\n'.join(nuevas_lineas)

# ── Dashboard builder ─────────────────────────────────────────────────────────

def build_dashboard(csv_data, logo_b64):
    def n(v):
        try: return float(v) if v else 0
        except: return 0

    by_date = defaultdict(dict)
    HOTELES_SET = ["HJ Plaza La Ribera","Howard Johnson Cariló","Soho Park","HJ Bahia Blanca"]
    HOTEL_COLORS = {"HJ Plaza La Ribera":"#378ADD","Howard Johnson Cariló":"#1D9E75",
                    "Soho Park":"#D85A30","HJ Bahia Blanca":"#8B6914"}
    HOTEL_HAB = {"HJ Plaza La Ribera":104,"Howard Johnson Cariló":120,"Soho Park":43,"HJ Bahia Blanca":79}

    for r in csv.DictReader(io.StringIO(csv_data.strip())):
        f, h = r['Fecha'], r['Hotel']
        # Ocupación GTH: usar Dia_Ocup_GTH si existe y es > 0, sino Dia_Ocup
        ocup_gth = n(r.get('Dia_Ocup_GTH', '0'))
        ocup_display = ocup_gth if ocup_gth > 0 else n(r['Dia_Ocup'])

        by_date[f][h] = {
            "hotel": h, "color": r['Color'], "hab": int(n(r['Hab'])), "manager": r['Manager'],
            "d_ocup":     ocup_display,
            "d_ocup_arion": n(r['Dia_Ocup']),
            "d_hab_ocup": int(n(r.get('Dia_Hab_Ocup', '0'))),
            "d_house_use": int(n(r.get('Dia_House_Use', '0'))),
            "d_adr":      n(r['Dia_ADR']),    "d_revpar":   n(r['Dia_RevPAR']),
            "d_lleg":     int(n(r['Dia_Lleg'])), "d_sal": int(n(r['Dia_Sal'])),
            "d_rev":      n(r['Dia_Rev']),    "d_rooms":    n(r['Dia_Rooms']),   "d_ayb": n(r['Dia_AyB']),
            "d_rev_aa":   n(r['Dia_Rev_AA']), "d_rooms_aa": n(r['Dia_Rooms_AA']),"d_ayb_aa": n(r['Dia_AyB_AA']),
            "m_ocup":     n(r['Mes_Ocup']),   "m_adr":      n(r['Mes_ADR']),    "m_revpar": n(r['Mes_RevPAR']),
            "m_lleg":     int(n(r['Mes_Lleg'])),
            "m_rev":      n(r['Mes_Rev']),    "m_rooms":    n(r['Mes_Rooms']),   "m_ayb": n(r['Mes_AyB']),
            "m_rev_aa":   n(r['Mes_Rev_AA']), "m_rooms_aa": n(r['Mes_Rooms_AA']),"m_ayb_aa": n(r['Mes_AyB_AA']),
            "aa_ocup":    n(r['AA_Ocup']),    "aa_adr":     n(r['AA_ADR']),     "aa_revpar": n(r['AA_RevPAR']),
            "sin_k007": n(r['Dia_Ocup'])==0 and n(r['Dia_Rev'])==0 and n(r['Mes_Rev'])>0
        }

    fechas = sorted(by_date.keys(), key=lambda d: [int(x) for x in d.split('/')[::-1]], reverse=True)
    DB_JSON      = json.dumps({f: by_date[f] for f in fechas}, ensure_ascii=False)
    FECHAS_JSON  = json.dumps(fechas)
    HOTELES_JSON = json.dumps([{"nombre":h,"color":HOTEL_COLORS[h],"hab":HOTEL_HAB[h]} for h in HOTELES_SET], ensure_ascii=False)

    with open("template_dashboard.html", encoding="utf-8") as f_t:
        html = f_t.read()

    def replace_const(html, name, value):
        start = html.find(f'const {name} = ')
        end   = html.find(';\n', start) + 2
        return html[:start] + f'const {name} = {value};\n' + html[end:]

    html = replace_const(html, 'DB',      DB_JSON)
    html = replace_const(html, 'FECHAS',  FECHAS_JSON)
    html = replace_const(html, 'HOTELES', HOTELES_JSON)
    return html

def build_ejecutivo(csv_data, logo_b64):
    with open("template_ejecutivo.html", encoding="utf-8") as f_t:
        return f_t.read()

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== GTH Dashboard Generator ===", flush=True)
    gh_token = os.environ.get("GH_TOKEN", "")
    logo_b64 = os.environ.get("LOGO_B64", "")
    sa_json  = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)
    print(f"Drive SA: {'OK' if sa_json else 'FALTA'}", flush=True)

    ayer        = datetime.date.today() - datetime.timedelta(days=1)
    fecha_str   = ayer.strftime("%d/%m/%Y")
    fecha_drive = ayer.strftime("%Y.%m.%d")
    print(f"Procesando fecha: {fecha_str}", flush=True)

    print("Leyendo datos.csv...", flush=True)
    try:
        csv_data, csv_sha = github_get("datos.csv", gh_token)
        print(f"CSV: {len(csv_data.strip().split(chr(10)))-1} registros", flush=True)
    except Exception as e:
        print(f"Error leyendo CSV: {e}", flush=True); sys.exit(1)

    # Normalizar CSV histórico para que tenga las nuevas columnas
    csv_data = normalizar_csv(csv_data)

    if not sa_json:
        print("Sin Drive SA — usando CSV existente", flush=True)
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
            "google-auth", "google-auth-httplib2", "google-api-python-client", "pdfminer.six"], check=True)

        print("Conectando a Drive...", flush=True)
        service = get_drive_service(sa_json)
        filas_nuevas = []

        for hotel, folder_id in CARPETAS.items():
            print(f"  {hotel}...", flush=True)
            pdf = buscar_pdf(service, folder_id, fecha_drive)
            if not pdf:
                print(f"    Sin PDF del {fecha_drive}", flush=True)
                continue
            print(f"    Leyendo {pdf['name']}...", flush=True)
            texto = exportar_pdf_texto(service, pdf["id"])
            if not texto or len(texto) < 50:
                print(f"    Texto insuficiente", flush=True)
                continue
            print(f"    Texto: {len(texto)} chars", flush=True)
            print(f"    FULL TEXT: {repr(texto[:3000])}", flush=True)

            fila = extraer_fila_k007(texto, hotel, fecha_str)
            campos = fila.split(',')
            print(f"    Parser: Ocup={campos[5]}% ADR={campos[6]} Rev={campos[10]} OcupGTH={campos[31]}%", flush=True)

            # Fallback Claude si ADR o Revenue son 0
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key and (campos[6] == '0' or campos[10] == '0'):
                print(f"    Completando con Claude API...", flush=True)
                datos_parciales = f"Ocup={campos[5]}%, Llegadas={campos[8]}, Salidas={campos[9]}"
                fila_claude = claude_completar_datos(api_key, hotel, fecha_str, texto, datos_parciales)
                if fila_claude and fila_claude.count(",") >= 31:
                    fila = fila_claude
                    campos = fila.split(",")
                    print(f"    Claude: Ocup={campos[5]}% ADR={campos[6]} Rev={campos[10]}", flush=True)

            filas_nuevas.append(fila)

        if filas_nuevas:
            print(f"{len(filas_nuevas)} hoteles OK — actualizando CSV", flush=True)
            lineas = csv_data.strip().split('\n')
            header = lineas[0]
            lineas_sin_fecha = [l for l in lineas[1:] if not l.startswith(fecha_str + ',')]
            eliminadas = len(lineas[1:]) - len(lineas_sin_fecha)
            if eliminadas:
                print(f"  Pisando {eliminadas} filas existentes del {fecha_str}", flush=True)
            csv_nuevo = header + '\n' + '\n'.join(filas_nuevas) + '\n' + '\n'.join(lineas_sin_fecha)
            github_put("datos.csv", csv_nuevo.encode("utf-8"), gh_token, sha=csv_sha)
            csv_data = csv_nuevo
        else:
            print(f"Sin PDFs del {fecha_str}", flush=True)

    print("Generando HTMLs...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars | Ejecutivo: {len(html_ejec):,} chars", flush=True)
    print("Subiendo...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))
    print("=== DONE ===", flush=True)
