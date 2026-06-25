#!/usr/bin/env python3
"""GTH Dashboard Generator — GitHub Actions — v7 (fixes: CSV legacy, ADR fallback, RevPAR BBA)"""
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
HOTELES_LIST = ["HJ Plaza La Ribera","Howard Johnson Cariló","Soho Park","HJ Bahia Blanca"]

CSV_HEADER = (
    "Fecha,Hotel,Color,Hab,Manager,"
    "Dia_Ocup,Dia_ADR,Dia_RevPAR,Dia_Lleg,Dia_Sal,"
    "Dia_Rev,Dia_Rooms,Dia_AyB,"
    "Dia_Rev_AA,Dia_Rooms_AA,Dia_AyB_AA,"
    "Mes_Ocup,Mes_ADR,Mes_RevPAR,Mes_Lleg,"
    "Mes_Rev,Mes_Rooms,Mes_AyB,"
    "Mes_Rev_AA,Mes_Rooms_AA,Mes_AyB_AA,"
    "AA_Ocup,AA_ADR,AA_RevPAR,"
    "Dia_Hab_Ocup,Dia_House_Use,Dia_Complimentary,Dia_Ocup_GTH,"
    "Mes_Hab_Ocup,Mes_House_Use,Mes_Complimentary,Mes_Ocup_GTH"
)

# ── GitHub ────────────────────────────────────────────────────────────────────

def github_get(path, token):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    headers = {"Authorization":f"token {token}","Accept":"application/vnd.github.v3+json","User-Agent":"GTH"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

def github_put(path, content_bytes, token, sha=None):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers = {"Authorization":f"token {token}","Accept":"application/vnd.github.v3+json",
               "Content-Type":"application/json","User-Agent":"GTH"}
    body = {"message":f"GTH · {datetime.date.today().strftime('%d/%m/%Y')} · auto",
            "content":base64.b64encode(content_bytes).decode(),"branch":BRANCH}
    if sha: body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            print(f"  ✅ {path}: {resp['commit']['sha'][:8]}", flush=True); return True
    except urllib.error.HTTPError as e:
        print(f"  ❌ {path}: {e.code} {e.read().decode()[:200]}", flush=True); return False

def get_sha(path, token):
    try: _, sha = github_get(path, token); return sha
    except: return None

# ── Drive ─────────────────────────────────────────────────────────────────────

def get_drive_service(sa_json):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json), scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive","v3",credentials=creds)

def buscar_pdf(service, folder_id, fecha_drive):
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and name contains '{fecha_drive}'"
    result = service.files().list(q=query, fields="files(id,name)", pageSize=5).execute()
    files = result.get("files",[])
    if files:
        files.sort(key=lambda x:x["name"], reverse=True)
        return files[0]
    return None

def listar_todos_pdfs(service, folder_id):
    """Lista todos los PDFs de una carpeta con paginación"""
    todos = []
    page_token = None
    query = f"'{folder_id}' in parents and mimeType='application/pdf'"
    while True:
        kwargs = {"q":query,"fields":"nextPageToken,files(id,name)","pageSize":100}
        if page_token: kwargs["pageToken"] = page_token
        result = service.files().list(**kwargs).execute()
        todos.extend(result.get("files",[]))
        page_token = result.get("nextPageToken")
        if not page_token: break
    return todos

def nombre_a_fecha(nombre):
    """
    Extrae fecha del nombre del PDF: formato YYYY.MM.DD → DD/MM/YYYY
    Ej: 'K007_2026.05.15_HJLaRibera.pdf' → '15/05/2026'
    """
    m = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', nombre)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return None

def exportar_pdf_texto(service, file_id):
    import io as _io
    from googleapiclient.http import MediaIoBaseDownload
    request = service.files().get_media(fileId=file_id)
    buf = _io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done: _, done = dl.next_chunk()
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

# ── Parsers PDF ───────────────────────────────────────────────────────────────

def es_formato_bba(texto):
    return bool(re.search(r'[\d\.]+\nPorcentaje de Ocupaci', texto))

def extraer_hab_house_normal(dia, mes):
    """PLR/Cariló/Soho: lee directo de las listas ya extraídas por get_sec()
    (las mismas que ya dan bien %Ocup/Llegadas/Salidas). Posiciones fijas
    validadas contra PDF real (Cariló 2026.06.24.pdf, texto completo
    pegado por el usuario, cruzado contra valores ya correctos en
    pantalla):
        índice 5  = Habitaciones Ocupadas
        índice 22 = Complimentary
        índice 23 = House Use
    Antes se usaba un regex separado buscando 'Habitaciones Ocupadas\\s+
    (num)\\s+(num)' directo sobre el texto crudo, que nunca matcheaba con
    el orden real que produce pdfminer — por eso este campo daba siempre 0."""
    hab_dia  = ni(dia, 5) if dia else 0
    hu_dia   = ni(dia, 23) if dia else 0
    comply_dia = ni(dia, 22) if dia else 0
    hab_mes  = ni(mes, 5) if mes else 0
    hu_mes   = ni(mes, 23) if mes else 0
    comply_mes = ni(mes, 22) if mes else 0
    return hab_dia, hu_dia, comply_dia, hab_mes, hu_mes, comply_mes

def extraer_hab_house_bba(texto):
    """BBA (Crystal Reports): el valor del DÍA aparece ANTES del label, en su
    propia línea ('0\\nComplimentary', '0\\nHouse Use'). Patrón validado contra
    PDF real (2026.06.19.pdf, 2026.06.23.pdf)."""
    hab_dia=hu_dia=comply_dia=0
    m = re.search(r'([\d,]+)\nHabitaciones Ocupadas', texto)
    if m: hab_dia = int(m.group(1).replace(',',''))
    m = re.search(r'([\d,]+)\nHouse Use', texto)
    if m: hu_dia = int(m.group(1).replace(',',''))
    m = re.search(r'([\d,]+)\nComplimentary', texto)
    if m: comply_dia = int(m.group(1).replace(',',''))
    return hab_dia, hu_dia, comply_dia

def calcular_ocup_gth(hab_ocup, house_use, comply, hab_total):
    """Ocupación 'real' GTH del DÍA: excluye House Use y Complimentary."""
    if hab_total <= 0:
        return None
    neto = hab_ocup - house_use - comply
    if neto < 0: neto = 0
    return round(neto / hab_total * 100, 2)

def calcular_ocup_mes_gth(hab_ocup_mes, house_use_mes, comply_mes, ocup_arion_mes_pct):
    """Ocupación 'real' GTH del MES: excluye House Use y Complimentary.
    La capacidad mensual se DERIVA del % crudo de Arion."""
    if not ocup_arion_mes_pct or ocup_arion_mes_pct <= 0 or hab_ocup_mes <= 0:
        return None
    capacidad_mes = hab_ocup_mes / (ocup_arion_mes_pct / 100)
    if capacidad_mes <= 0:
        return None
    neto = hab_ocup_mes - house_use_mes - comply_mes
    if neto < 0: neto = 0
    return round(neto / capacidad_mes * 100, 2)

def get_sec(texto, label, terminators):
    le = re.escape(label)
    pat = rf'\b{le}\b\s*\n([\s\S]+?)(?=\n\s*(?:{terminators}|\Z))'
    m = re.search(pat, texto)
    if not m: return []
    return re.findall(r'[\d,]+\.?\d*', m.group(1))

def ni(lst,idx):
    try: return int(float(str(lst[idx]).replace(',','')))
    except: return 0

def nf(lst,idx):
    try: return float(str(lst[idx]).replace(',',''))
    except: return 0.0

ADR_IDX_NORMAL = 32  # índice 0-based de "Tarifa Promedio" en la lista columna-
# major de un K007 normal (PLR/Cariló/Soho). CONFIRMADO con el texto real
# completo de Cariló 2026.06.24.pdf, cruzando contra valores que ya estaban
# correctos en el dashboard (dia[7]=%Ocup=2.56, dia[9]=Llegadas=1,
# dia[10]=Salidas=0 — los 3 coinciden exactamente). A partir de ahí, contando
# los 45 labels del reporte hasta "Tarifa Promedio", el índice es 32.
ADR_IDX_TOT_HAB = 33  # +1 si el reporte tiene la columna extra "TOTAL REVENUE
# / HAB" (sin validar todavía — asumido por simetría con rooms_off/ayb_off,
# que ya tenían ese mismo ajuste condicional en el código original).

def find_adr_idx(nums):
    """[OBSOLETO desde v8 — ya no se usa, se deja sólo por compatibilidad].
    Buscaba el ADR por rango numérico (50.000-600.000). Se abandonó porque
    cuando el ADR real cae fuera de ese rango (ej. $45.455, bajo el piso de
    50.000), el heurístico se salta el campo correcto y agarra el SIGUIENTE
    valor que sí cae en rango (ej. REVPAC), desplazando todos los offsets
    relativos (RevPAR, Rooms, AA&BB) hacia campos equivocados. Confirmado con
    el PDF real de Cariló 2026.06.24 (Tarifa Promedio real=45.455 vs ADR
    mostrado=90.661=REVPAC, exactamente 2 posiciones después)."""
    for i in range(20, len(nums)):
        try:
            v = float(str(nums[i]).replace(',',''))
            if 50000 <= v <= 600000: return i
        except: pass
    return None

def extraer_manager_normal(texto):
    pat = re.compile(r'^[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,15}(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,15}){1,2}$')
    lineas = texto.strip().split("\n")
    for linea in lineas[:5]:
        if pat.match(linea.strip()): return linea.strip()
    for linea in reversed(lineas):
        if pat.match(linea.strip()): return linea.strip()
    return "Sin datos"

def extraer_fila_normal(texto, hotel, fecha_display):
    info = HOTEL_INFO[hotel]
    manager = extraer_manager_normal(texto)
    NEXT_DIA   = r'Mes\b|Año\b|DiaAA\b|Dia AA|Habitaciones'
    NEXT_MES   = r'Año\b|DiaAA\b|MesAA\b|Dia AA|Mes AA|Habitaciones'
    NEXT_DIAAA = r'MesAA\b|Mes AA|AñoA\b|Año A|Habitaciones'
    NEXT_MESAA = r'AñoA\b|Año A|Habitaciones'
    dia    = get_sec(texto,'Dia',   NEXT_DIA)
    mes    = get_sec(texto,'Mes',   NEXT_MES)
    dia_aa = get_sec(texto,'DiaAA', NEXT_DIAAA) or get_sec(texto,'Dia AA',NEXT_DIAAA)
    mes_aa = get_sec(texto,'MesAA', NEXT_MESAA) or get_sec(texto,'Mes AA',NEXT_MESAA)
    tiene_tot_hab = 'TOTAL REVENUE / HAB' in texto.upper()
    rooms_off = 4 if tiene_tot_hab else 3
    ayb_off   = 5 if tiene_tot_hab else 4
    s_fijo = ADR_IDX_TOT_HAB if tiene_tot_hab else ADR_IDX_NORMAL
    def get_kpis(sec):
        if not sec or len(sec) <= s_fijo:
            return {'adr':0,'rp':0,'rooms':0,'ayb':0,'rev':ni(sec,-2) if len(sec)>=2 else 0}
        return {'adr':ni(sec,s_fijo),'rp':ni(sec,s_fijo+1),'rooms':ni(sec,s_fijo+rooms_off),'ayb':ni(sec,s_fijo+ayb_off),'rev':ni(sec,-2) if len(sec)>=2 else 0}
    d=get_kpis(dia); m=get_kpis(mes); aa=get_kpis(dia_aa); maa=get_kpis(mes_aa)
    dia_ocup=nf(dia,7); dia_lleg=ni(dia,9); dia_sal=ni(dia,10)
    mes_ocup=nf(mes,7); mes_lleg=ni(mes,9)
    aa_ocup=nf(dia_aa,7) if dia_aa else 0.0

    hab_ocup, house_use, comply, hab_ocup_mes, house_use_mes, comply_mes = extraer_hab_house_normal(dia, mes)

    ocup_gth = calcular_ocup_gth(hab_ocup, house_use, comply, info['hab'])
    if ocup_gth is None: ocup_gth = 0.0
    print(f"    GTH Ocup Dia: ({hab_ocup}-{house_use}-{comply})/{info['hab']} = {ocup_gth}%", flush=True)

    mes_ocup_gth = calcular_ocup_mes_gth(hab_ocup_mes, house_use_mes, comply_mes, mes_ocup)
    if mes_ocup_gth is None: mes_ocup_gth = 0.0
    print(f"    GTH Ocup Mes: ({hab_ocup_mes}-{house_use_mes}-{comply_mes})/cap.implícita = {mes_ocup_gth}% (Arion crudo: {mes_ocup}%)", flush=True)

    return (f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
            f"{dia_ocup},{d['adr']},{d['rp']},{dia_lleg},{dia_sal},"
            f"{d['rev']},{d['rooms']},{d['ayb']},"
            f"{aa['rev']},{aa['rooms']},{aa['ayb']},"
            f"{mes_ocup},{m['adr']},{m['rp']},{mes_lleg},"
            f"{m['rev']},{m['rooms']},{m['ayb']},"
            f"{maa['rev']},{maa['rooms']},{maa['ayb']},"
            f"{aa_ocup},{aa['adr']},{aa['rp']},"
            f"{hab_ocup},{house_use},{comply},{ocup_gth},"
            f"{hab_ocup_mes},{house_use_mes},{comply_mes},{mes_ocup_gth}")

def extraer_fila_bba(texto, hotel, fecha_display):
    info = HOTEL_INFO[hotel]
    manager = "Sin datos"
    mgr_m = re.match(r'^([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})\s*\n', texto.strip())
    if mgr_m: manager = mgr_m.group(1)
    def vbl(label):
        m = re.search(r'([\d,\.]+)\n'+re.escape(label), texto)
        return float(m.group(1).replace(',','')) if m else 0.0
    NEXT_MES = r'Año\b|DiaAA\b|MesAA\b|AñoA\b|Habitaciones'
    mes_sec = get_sec(texto,'Mes',NEXT_MES)
    dia_ocup=vbl('Porcentaje de Ocupación'); dia_lleg=int(vbl('Cantidad de Llegadas'))
    dia_sal=int(vbl('Cantidad de Salidas')); dia_adr=int(vbl('Tarifa Promedio'))
    dia_ayb_m=re.search(r'([\d,]+)\nAA[&\\]+BB',texto)
    dia_ayb=int(float(dia_ayb_m.group(1).replace(',',''))) if dia_ayb_m else 0
    dia_rev_m=re.search(r'([\d,]+)\nHotel Revenue\n',texto)
    dia_rev=int(float(dia_rev_m.group(1).replace(',',''))) if dia_rev_m else 0
    # NOTA: patrón validado contra pdfminer real (2026.06.19.pdf) — el orden
    # correcto acá ES 'REVPAR\n(numero)' (label antes del número). Un intento
    # previo de "corregir" esto a la inversa fue un error, basado en evidencia
    # del motor de extracción de Drive (distinto a pdfminer), no del texto real.
    rp_m=re.search(r'REVPAR\n([\d,]+)',texto)
    dia_rp=int(float(rp_m.group(1).replace(',',''))) if rp_m else 0
    if mes_sec and len(mes_sec)>35:
        mes_ocup=nf(mes_sec,7); mes_lleg=ni(mes_sec,9)
        # Índice fijo ADR_IDX_NORMAL (32) = "Tarifa Promedio", consistente con
        # los índices ya validados contra PDF real de BBA (5, 22, 23 más
        # abajo) que pertenecen a la MISMA lista de 45 labels.
        mes_adr=ni(mes_sec,32); mes_rp=ni(mes_sec,33)
        mes_rooms=ni(mes_sec,36); mes_ayb=ni(mes_sec,37)
        mes_rev=ni(mes_sec,-2) if len(mes_sec)>=2 else 0
    else:
        mes_ocup=mes_lleg=mes_adr=mes_rp=mes_rooms=mes_ayb=mes_rev=0

    # Mes: Hab_Ocup/House_Use/Complimentary por posición fija dentro de mes_sec
    # (validado contra 2026.06.19.pdf real: mes_sec[5]=Hab_Ocup, [22]=Comply,
    # [23]=House_Use).
    if mes_sec and len(mes_sec) > 23:
        hab_ocup_mes = ni(mes_sec, 5)
        comply_mes = ni(mes_sec, 22)
        house_use_mes = ni(mes_sec, 23)
    else:
        hab_ocup_mes = comply_mes = house_use_mes = 0

    hab_ocup, house_use, comply = extraer_hab_house_bba(texto)

    ocup_gth = calcular_ocup_gth(hab_ocup, house_use, comply, info['hab'])
    if ocup_gth is None: ocup_gth = 0.0
    print(f"    GTH Ocup BBA Dia: ({hab_ocup}-{house_use}-{comply})/{info['hab']} = {ocup_gth}%", flush=True)

    mes_ocup_gth = calcular_ocup_mes_gth(hab_ocup_mes, house_use_mes, comply_mes, mes_ocup)
    if mes_ocup_gth is None: mes_ocup_gth = 0.0
    print(f"    GTH Ocup BBA Mes: ({hab_ocup_mes}-{house_use_mes}-{comply_mes})/cap.implícita = {mes_ocup_gth}% (Arion crudo: {mes_ocup}%)", flush=True)
    print(f"    BBA Dia_ADR={dia_adr} Dia_RevPAR={dia_rp}", flush=True)

    return (f"{fecha_display},{hotel},{info['color']},{info['hab']},{manager},"
            f"{dia_ocup},{dia_adr},{dia_rp},{dia_lleg},{dia_sal},"
            f"{dia_rev},0,{dia_ayb},"
            f"0,0,0,"
            f"{mes_ocup},{mes_adr},{mes_rp},{mes_lleg},"
            f"{mes_rev},{mes_rooms},{mes_ayb},"
            f"0,0,0,"
            f"0.0,0,0,"
            f"{hab_ocup},{house_use},{comply},{ocup_gth},"
            f"{hab_ocup_mes},{house_use_mes},{comply_mes},{mes_ocup_gth}")

def extraer_fila_k007(texto, hotel, fecha_display):
    if hotel == "HJ Bahia Blanca" or es_formato_bba(texto):
        return extraer_fila_bba(texto, hotel, fecha_display)
    return extraer_fila_normal(texto, hotel, fecha_display)

# ── Claude fallback ───────────────────────────────────────────────────────────

def claude_completar_datos(api_key, hotel, fecha, texto_pdf, datos_parciales):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json"}
    info = HOTEL_INFO[hotel]
    prompt = f"""Del Manager Report K007 de {hotel} del {fecha}, extraé los datos.
TEXTO: {texto_pdf[:4000]}
Datos parciales: {datos_parciales}
Respondé SOLO con CSV de 37 campos:
{fecha},{hotel},{info['color']},{info['hab']},[Manager],[Dia_Ocup%],[Dia_ADR],[Dia_RevPAR],[Dia_Lleg],[Dia_Sal],[Dia_Rev],[Dia_Rooms],[Dia_AyB],[Dia_Rev_AA],[Dia_Rooms_AA],[Dia_AyB_AA],[Mes_Ocup%],[Mes_ADR],[Mes_RevPAR],[Mes_Lleg],[Mes_Rev],[Mes_Rooms],[Mes_AyB],[Mes_Rev_AA],[Mes_Rooms_AA],[Mes_AyB_AA],[AA_Ocup%],[AA_ADR],[AA_RevPAR],[Dia_Hab_Ocup],[Dia_House_Use],[Dia_Complimentary],[Dia_Ocup_GTH],[Mes_Hab_Ocup],[Mes_House_Use],[Mes_Complimentary],[Mes_Ocup_GTH]
Reglas: Revenue SIN IVA.
Dia_Complimentary / Mes_Complimentary = valores de la fila "Complimentary", columnas Dia y Mes.
Dia_Ocup_GTH = max(0, Dia_Hab_Ocup - Dia_House_Use - Dia_Complimentary) / Hab * 100.
Mes_Ocup_GTH = max(0, Mes_Hab_Ocup - Mes_House_Use - Mes_Complimentary) / (Mes_Hab_Ocup / (Mes_Ocup%/100)) * 100.
Si Tarifa Promedio (ADR) de un período es 0 o no aparece, Dia_ADR/Mes_ADR = 0 (no inventar otro número).
0 si algún dato no aparece."""
    body = {"model":"claude-haiku-4-5","max_tokens":700,"messages":[{"role":"user","content":prompt}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            texto = resp["content"][0]["text"].strip()
            for linea in texto.split("\n"):
                linea = linea.strip()
                if linea.count(",") >= 36: return linea
        return None
    except Exception as e:
        print(f"    Claude API error: {e}", flush=True); return None

# ── CSV helpers ───────────────────────────────────────────────────────────────

def normalizar_csv(csv_data):
    """Migra filas viejas al formato actual de 37 columnas.

    Dia_Complimentary va INSERTADO entre Dia_House_Use y Dia_Ocup_GTH — si se
    agregara al final en vez de insertarse ahí, el valor real de Dia_Ocup_GTH
    se leería con el nombre 'Dia_Complimentary' y la columna Dia_Ocup_GTH
    quedaría en cero (bug ya corregido en v6)."""
    lineas = csv_data.strip().split('\n')
    if 'Mes_Ocup_GTH' in lineas[0]:
        return csv_data
    n_nuevo = len(CSV_HEADER.split(','))  # 37
    nuevas = [CSV_HEADER]
    for linea in lineas[1:]:
        if not linea.strip(): continue
        campos = linea.split(',')
        n = len(campos)
        if n == 32:
            campos = campos[:31] + ['0'] + [campos[31]] + ['0','0','0','0']
        elif n == 33:
            campos = campos + ['0','0','0','0']
        elif n < n_nuevo:
            while len(campos) < n_nuevo:
                campos.append('0')
        nuevas.append(','.join(campos[:n_nuevo]))
    return '\n'.join(nuevas)

# ── Builders de datos ─────────────────────────────────────────────────────────

def nv(v):
    try: return float(v) if v else 0
    except: return 0

def build_dashboard_data(csv_data):
    """Genera DB, FECHAS, HOTELES para el dashboard operativo"""
    by_date = defaultdict(dict)
    for r in csv.DictReader(io.StringIO(csv_data.strip())):
        f, h = r['Fecha'], r['Hotel']

        ocup_gth = nv(r.get('Dia_Ocup_GTH','0'))
        hab_ocup = int(nv(r.get('Dia_Hab_Ocup','0')))
        house_use = int(nv(r.get('Dia_House_Use','0')))
        comply = int(nv(r.get('Dia_Complimentary','0')))
        ocup_display = ocup_gth if hab_ocup > 0 else nv(r['Dia_Ocup'])

        mes_ocup_gth = nv(r.get('Mes_Ocup_GTH','0'))
        mes_hab_ocup = int(nv(r.get('Mes_Hab_Ocup','0')))
        mes_house_use = int(nv(r.get('Mes_House_Use','0')))
        mes_comply = int(nv(r.get('Mes_Complimentary','0')))
        mes_ocup_display = mes_ocup_gth if mes_hab_ocup > 0 else nv(r['Mes_Ocup'])

        by_date[f][h] = {
            "hotel":h,"color":r['Color'],"hab":int(nv(r['Hab'])),"manager":r['Manager'],
            "d_ocup":ocup_display,"d_ocup_arion":nv(r['Dia_Ocup']),
            "d_hab_ocup":hab_ocup,"d_house_use":house_use,"d_comply":comply,
            "d_adr":nv(r['Dia_ADR']),"d_revpar":nv(r['Dia_RevPAR']),
            "d_lleg":int(nv(r['Dia_Lleg'])),"d_sal":int(nv(r['Dia_Sal'])),
            "d_rev":nv(r['Dia_Rev']),"d_rooms":nv(r['Dia_Rooms']),"d_ayb":nv(r['Dia_AyB']),
            "d_rev_aa":nv(r['Dia_Rev_AA']),"d_rooms_aa":nv(r['Dia_Rooms_AA']),"d_ayb_aa":nv(r['Dia_AyB_AA']),
            "m_ocup":mes_ocup_display,"m_ocup_arion":nv(r['Mes_Ocup']),
            "m_hab_ocup":mes_hab_ocup,"m_house_use":mes_house_use,"m_comply":mes_comply,
            "m_adr":nv(r['Mes_ADR']),"m_revpar":nv(r['Mes_RevPAR']),
            "m_lleg":int(nv(r['Mes_Lleg'])),"m_rev":nv(r['Mes_Rev']),
            "m_rooms":nv(r['Mes_Rooms']),"m_ayb":nv(r['Mes_AyB']),
            "m_rev_aa":nv(r['Mes_Rev_AA']),"m_rooms_aa":nv(r['Mes_Rooms_AA']),"m_ayb_aa":nv(r['Mes_AyB_AA']),
            "aa_ocup":nv(r['AA_Ocup']),"aa_adr":nv(r['AA_ADR']),"aa_revpar":nv(r['AA_RevPAR']),
            "sin_k007": nv(r['Dia_Ocup'])==0 and nv(r['Dia_Rev'])==0 and nv(r['Mes_Rev'])>0
        }
    fechas = sorted(by_date.keys(), key=lambda d:[int(x) for x in d.split('/')[::-1]], reverse=True)
    return (
        json.dumps({f:by_date[f] for f in fechas}, ensure_ascii=False),
        json.dumps(fechas),
        json.dumps([{"nombre":h,"color":HOTEL_INFO[h]["color"],"hab":HOTEL_INFO[h]["hab"]} for h in HOTELES_LIST], ensure_ascii=False)
    )

def build_ejecutivo_data(csv_data):
    """Genera todas las constantes JS para el informe ejecutivo"""
    NOMBRES_MESES = {'01':'Ene','02':'Feb','03':'Mar','04':'Abr','05':'May',
                     '06':'Jun','07':'Jul','08':'Ago','09':'Sep','10':'Oct','11':'Nov','12':'Dic'}
    by_month = defaultdict(lambda: defaultdict(dict))
    for r in csv.DictReader(io.StringIO(csv_data.strip())):
        partes = r['Fecha'].split('/')
        mk = f"{partes[1]}/{partes[2]}"
        by_month[mk][r['Hotel']] = r

    meses_ord = sorted(by_month.keys(), key=lambda m:(int(m.split('/')[1]),int(m.split('/')[0])))
    meses_labels = [f"{NOMBRES_MESES[mk.split('/')[0]]} {mk.split('/')[1]}" for mk in meses_ord]

    series = {k:{h:[] for h in HOTELES_LIST} for k in ['ocup','adr','rp','rev']}
    for mk in meses_ord:
        for h in HOTELES_LIST:
            r = by_month[mk].get(h)
            series['ocup'][h].append(round(nv(r['Mes_Ocup']),2) if r else None)
            series['adr'][h].append(round(nv(r['Mes_ADR'])/1000,1) if r else None)
            series['rp'][h].append(round(nv(r['Mes_RevPAR'])/1000,1) if r else None)
            series['rev'][h].append(round(nv(r['Mes_Rev'])/1e6,1) if r else None)

    ultimo = meses_ord[-1] if meses_ord else None
    bench = {}
    if ultimo:
        for h in HOTELES_LIST:
            r = by_month[ultimo].get(h)
            if r:
                bench[h] = {"Hab":nv(r['Hab']),"Dia_Ocup":nv(r['Dia_Ocup']),"Dia_ADR":nv(r['Dia_ADR']),
                            "Dia_RevPAR":nv(r['Dia_RevPAR']),"Dia_Rev":nv(r['Dia_Rev']),
                            "Mes_Ocup":nv(r['Mes_Ocup']),"Mes_ADR":nv(r['Mes_ADR']),
                            "Mes_RevPAR":nv(r['Mes_RevPAR']),"Mes_Rev":nv(r['Mes_Rev']),
                            "Mes_Rooms":nv(r['Mes_Rooms']),"Mes_AyB":nv(r['Mes_AyB'])}

    scatter = []
    for h in HOTELES_LIST:
        puntos = []
        for i,mk in enumerate(meses_ord):
            r = by_month[mk].get(h)
            if r and nv(r['Mes_Ocup'])>0:
                puntos.append({"x":round(nv(r['Mes_Ocup']),2),"y":round(nv(r['Mes_ADR'])/1000,1),"mes":meses_labels[i]})
        scatter.append({"nombre":h,"color":HOTEL_INFO[h]["color"],"puntos":puntos})

    badge = meses_labels[-1] if meses_labels else "—"
    hoteles_con_datos = sum(1 for h in HOTELES_LIST if by_month[ultimo].get(h)) if ultimo else 0
    total_rev = sum(nv(by_month[ultimo].get(h,{}).get('Mes_Rev',0)) for h in HOTELES_LIST if by_month[ultimo].get(h)) if ultimo else 0
    avg_ocup = (sum(nv(by_month[ultimo].get(h,{}).get('Mes_Ocup',0)) for h in HOTELES_LIST if by_month[ultimo].get(h)) / hoteles_con_datos) if hoteles_con_datos>0 else 0

    return {
        "MESES_EJ":     json.dumps(meses_labels),
        "SERIES_OCUP":  json.dumps(series['ocup'], ensure_ascii=False),
        "SERIES_ADR":   json.dumps(series['adr'],  ensure_ascii=False),
        "SERIES_RP":    json.dumps(series['rp'],   ensure_ascii=False),
        "SERIES_REV":   json.dumps(series['rev'],  ensure_ascii=False),
        "BENCH":        json.dumps(bench,           ensure_ascii=False),
        "SCATTER":      json.dumps(scatter,         ensure_ascii=False),
        "BADGE_MES":    badge,
        "TOTAL_REV_MES":f"{round(total_rev/1e6,1)}",
        "AVG_OCUP":     f"{round(avg_ocup,1)}",
        "HOTELES_COUNT":str(hoteles_con_datos),
    }

# ── HTML builders ─────────────────────────────────────────────────────────────

def replace_const(html, name, value):
    import re as _re
    m = _re.search(rf'const {_re.escape(name)}\s*=\s*', html)
    if not m:
        print(f"  ⚠️ replace_const: no encontró 'const {name}'", flush=True)
        return html
    start = m.start()
    end = html.find(';\n', m.end()) + 2
    return html[:start] + f'const {name} = {value};\n' + html[end:]

def replace_text(html, marker, value):
    return html.replace(f'[[{marker}]]', value)

def build_html(csv_data, logo_b64):
    """Genera el único HTML unificado (index.html)"""
    DB_JSON, FECHAS_JSON, HOTELES_JSON = build_dashboard_data(csv_data)
    ej = build_ejecutivo_data(csv_data)

    with open("template_dashboard.html", encoding="utf-8") as f_t:
        html = f_t.read()

    if logo_b64:
        html = html.replace('LOGO_PLACEHOLDER', logo_b64)

    html = replace_const(html, 'DB',      DB_JSON)
    html = replace_const(html, 'FECHAS',  FECHAS_JSON)
    html = replace_const(html, 'HOTELES', HOTELES_JSON)

    html = replace_const(html, 'MESES_EJ',    ej['MESES_EJ'])
    html = replace_const(html, 'SERIES_OCUP', ej['SERIES_OCUP'])
    html = replace_const(html, 'SERIES_ADR',  ej['SERIES_ADR'])
    html = replace_const(html, 'SERIES_RP',   ej['SERIES_RP'])
    html = replace_const(html, 'SERIES_REV',  ej['SERIES_REV'])
    html = replace_const(html, 'BENCH',       ej['BENCH'])
    html = replace_const(html, 'SCATTER',     ej['SCATTER'])
    html = replace_text(html,  'BADGE_MES',   ej['BADGE_MES'])
    html = replace_text(html,  'TOTAL_REV',   ej['TOTAL_REV_MES'])
    html = replace_text(html,  'AVG_OCUP',    ej['AVG_OCUP'])
    html = replace_text(html,  'HOTELES_N',   ej['HOTELES_COUNT'])

    return html

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== GTH Dashboard Generator v7 (fixes: CSV legacy, ADR fallback, RevPAR BBA) ===", flush=True)
    gh_token = os.environ.get("GH_TOKEN","")
    logo_b64 = os.environ.get("LOGO_B64","")
    sa_json  = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON","")

    csv_data, csv_sha = github_get("datos.csv", gh_token)
    print(f"CSV: {len(csv_data.strip().split(chr(10)))-1} registros", flush=True)
    csv_data = normalizar_csv(csv_data)

    if sa_json:
        import subprocess
        subprocess.run([sys.executable,"-m","pip","install","-q",
            "google-auth","google-auth-httplib2","google-api-python-client","pdfminer.six"], check=True)

        service = get_drive_service(sa_json)
        api_key = os.environ.get("ANTHROPIC_API_KEY","")

        ya_procesados = set()
        for linea in csv_data.strip().split('\n')[1:]:
            if not linea.strip(): continue
            partes = linea.split(',')
            if len(partes) >= 2:
                ya_procesados.add(f"{partes[0]}|{partes[1]}")

        print(f"Ya procesados: {len(ya_procesados)} registros", flush=True)

        filas_nuevas = []

        for hotel, folder_id in CARPETAS.items():
            print(f"\n  {hotel} — escaneando Drive...", flush=True)
            try:
                pdfs = listar_todos_pdfs(service, folder_id)
            except Exception as e:
                print(f"    Error listando: {e}", flush=True); continue

            print(f"    {len(pdfs)} PDFs encontrados", flush=True)
            pdfs.sort(key=lambda x: x["name"])

            for pdf in pdfs:
                fecha_str = nombre_a_fecha(pdf["name"])
                if not fecha_str:
                    print(f"    Ignorando {pdf['name']} (sin fecha)", flush=True)
                    continue

                clave = f"{fecha_str}|{hotel}"
                if clave in ya_procesados:
                    continue

                print(f"    Procesando {pdf['name']} ({fecha_str})...", flush=True)
                try:
                    texto = exportar_pdf_texto(service, pdf["id"])
                except Exception as e:
                    print(f"    Error leyendo PDF: {e}", flush=True); continue

                if not texto or len(texto) < 50:
                    print(f"    Texto insuficiente", flush=True); continue

                print(f"    Texto: {len(texto)} chars", flush=True)
                print(f"    FULL TEXT: {repr(texto[:3000])}", flush=True)

                fila = extraer_fila_k007(texto, hotel, fecha_str)
                campos = fila.split(',')
                print(f"    Parser: Ocup={campos[5]}% ADR={campos[6]} RevPAR={campos[7]} Rev={campos[10]} | "
                      f"DiaComply={campos[31]} OcupGTH_Dia={campos[32]}% | "
                      f"MesComply={campos[35]} OcupGTH_Mes={campos[36]}%", flush=True)

                if api_key and (campos[6]=='0' or campos[10]=='0'):
                    print(f"    Completando con Claude API...", flush=True)
                    datos_p = f"Ocup={campos[5]}%, Lleg={campos[8]}, Sal={campos[9]}"
                    fc = claude_completar_datos(api_key, hotel, fecha_str, texto, datos_p)
                    if fc and fc.count(",")>=36:
                        fila=fc; campos=fila.split(",")
                        print(f"    Claude: Ocup={campos[5]}% ADR={campos[6]}", flush=True)

                filas_nuevas.append(fila)
                ya_procesados.add(clave)

        if filas_nuevas:
            print(f"\n{len(filas_nuevas)} filas nuevas — actualizando CSV", flush=True)
            lineas = csv_data.strip().split('\n')
            header = lineas[0]
            todas = lineas[1:] + filas_nuevas
            todas = [l for l in todas if l.strip()]
            def sort_key(l):
                try:
                    p = l.split(',')[0].split('/')
                    return (int(p[2]), int(p[1]), int(p[0]))
                except: return (0,0,0)
            todas.sort(key=sort_key, reverse=True)
            csv_nuevo = header + '\n' + '\n'.join(todas)
            _, csv_sha = github_get("datos.csv", gh_token)
            github_put("datos.csv", csv_nuevo.encode("utf-8"), gh_token, sha=csv_sha)
            csv_data = csv_nuevo
        else:
            print("\nNo hay PDFs nuevos para procesar", flush=True)

    print("\nGenerando HTML unificado...", flush=True)
    html = build_html(csv_data, logo_b64)
    print(f"HTML: {len(html):,} chars", flush=True)
    github_put("index.html", html.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    print("=== DONE ===", flush=True)
