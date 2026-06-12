#!/usr/bin/env python3
"""
GTH E/R Dashboard Generator
Descarga el Excel de Drive, extrae datos de todos los hoteles y genera el HTML.
"""

import os, sys, json, base64, re
import pandas as pd
import numpy as np
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io, requests

# Ã¢ÂÂÃ¢ÂÂ CONFIG Ã¢ÂÂÃ¢ÂÂ
FILE_ID = os.environ.get('ER_EXCEL_FILE_ID', '1giqR1a-KE6PD-WtrkR70uiuTDjWVRDsV')
OUTPUT_HTML = 'GTH_ER_Dashboard.html'

# Ã¢ÂÂÃ¢ÂÂ GOOGLE DRIVE AUTH Ã¢ÂÂÃ¢ÂÂ
def get_drive_service():
    creds_json = os.environ.get('GDRIVE_SERVICE_ACCOUNT_JSON') or os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not creds_json:
        raise ValueError("GDRIVE_SERVICE_ACCOUNT_JSON not set")
    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    return build('drive', 'v3', credentials=creds)

def download_excel(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf

# Ã¢ÂÂÃ¢ÂÂ DATA EXTRACTION Ã¢ÂÂÃ¢ÂÂ
MONTHS_ORDER = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
MONTHS_UPPER = [m.upper() for m in MONTHS_ORDER]

def norm_month(v):
    if not isinstance(v, str): return None
    s = v.strip().upper()
    return MONTHS_ORDER[MONTHS_UPPER.index(s)] if s in MONTHS_upper else None

def norm_month(v):
    if not isinstance(v, str): return None
    s = v.strip().upper()
    if s in MONTHS_UPPER:
        return MONTHS_ORDER[MONTHS_UPPER.index(s)]
    return None

def parse_yr(v):
    if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
        f = float(v)
        if 2018 <= f <= 2030: return int(f)
        f2 = round(f * 1000)
        if 2018 <= f2 <= 2030: return f2
    if isinstance(v, str):
        s = v.strip().replace("'","").replace(',','.')
        try:
            f = float(s)
            if 2018 <= f <= 2030: return int(f)
            f2 = round(f * 1000)
            if 2018 <= f2 <= 2030: return f2
        except: pass
    return None

def get_month_year_cols(df, month_row, year_row):
    row_m = list(df.iloc[month_row])
    row_y = list(df.iloc[year_row])
    cols, cur_m = [], None
    for i in range(len(row_m)):
        m = norm_month(row_m[i])
        if m: cur_m = m
        yr = parse_yr(row_y[i])
        if yr and cur_m:
            cols.append((i, cur_m, yr))
            cur_m = None
    return cols

def find_row(df, labels):
    if isinstance(labels, str): labels = [labels]
    for lbl in labels:
        mask = df[0] == lbl
        if mask.any(): return df[mask].index[0]
    return None

def gv_cell(df, ridx, ci, is_pct=False):
    v = df.iloc[ridx, ci]
    if isinstance(v, float) and np.isnan(v): return 0.0
    if isinstance(v, str):
        s = v.replace(',','').replace('%','').strip()
        if s in ('','#ÃÂ¡DIV/0!','#DIV/0!'): return 0.0
        try: f = float(s)
        except: return 0.0
    else:
        try: f = float(v)
        except: return 0.0
    return f/100 if is_pct and f > 1 else f

ER_LABELS = {
    'v_hab':    'Venta habitaciones',
    'v_ayb':    'Venta alimentos y bebidas',
    'v_total':  'TOTAL VENTAS',
    'cv_total': 'COSTO DE VENTAS',
    'nom':      'NOMINA',
    'otros_g':  'OTROS GASTOS',
    'util_dep': 'UTILIDAD DEPARTAMENTAL',
    'gnd':      'GASTOS NO DISTRIBUIDOS',
    'gop':      'UTILIDAD BRUTA OPERACIONAL (GOP)',
    'cf':       'TOTAL CARGOS FIJOS',
    'ut_ant':   'UTILIDAD ANTES DE REMUNERACION',
    'rem_op':   'Remuneracion operador',
    'ut_op':    'UTILIDAD OPERACIONAL',
    'ut_neta':  'UTILIDAD A DISTRIBUIR',
}
HAB_LABELS = {
    'hab_dis':  'Habitaciones disponibles',
    'hab_occ':  'Habitaciones ocupadas',
    'occ_pct':  ['%  ocupacion', '% ocupacion',% ocupación','%  ocupación','% Ocupación','%  Ocupación','Porcentaje de ocupación','Ocupación','% ocupacion','%  ocupacion',],
    'adr':      'Tarifa promedio',
}

def extract_hotel(df, hotel_name, er_month_row=5, er_year_row=6,
                  hab_month_row=None, hab_year_row=None):
    er_mc  = get_month_year_cols(df, er_month_row, er_year_row)
    hab_mc = get_month_year_cols(df, hab_month_row or er_month_row,
                                 hab_year_row or er_year_row)
    hab_map = {(yr, m): ci for ci, m, yr in hab_mc}

    ri_er  = {k: find_row(df, v) for k, v in ER_LABELS.items() if find_row(df, v) is not None}
    ri_hab = {k: find_row(df, v) for k, v in HAB_LABELS.items() if find_row(df, v) is not None}

    by_ym = {}
    for (ci, month, year) in er_mc:
        rec = {k: gv_cell(df, ridx, ci) for k, ridx in ri_er.items()}
        hab_ci = hab_map.get((year, month), ci)
        for k, ridx in ri_hab.items():
            if k == 'occ_pct':
                v = gv_cell(df, ridx, hab_ci)
                rec[k] = v/100 if v > 1 else v
            elif k == 'adr':
                v = gv_cell(df, ridx, hab_ci)
                rec[k] = v * 1000 if 0 < v < 500 else v
            else:
                rec[k] = gv_cell(df, ridx, hab_ci)
        rec['v_otros'] = max(0, rec.get('v_total',0) - rec.get('v_hab',0) - rec.get('v_ayb',0))
        rec['revpar']  = rec.get('adr',0) * rec.get('occ_pct',0)
        by_ym.setdefault(year, {})[month] = rec

    out = {'hotel': hotel_name, 'years': {}}
    for year in sorted(by_ym.keys()):
        months = by_ym[year]
        sm = sorted(months.keys(), key=lambda m: MONTHS_ORDER.index(m) if m in MONTHS_ORDER else 99)
        valid = [m for m in sm if months[m].get('v_total',0) > 0]
        if not valid: continue
        avg_k = {'occ_pct','adr','revpar'}
        all_k = list(ri_er.keys()) + list(ri_hab.keys()) + ['revpar','v_otros']
        ann = {}
        for k in all_k:
            vals = [months[m].get(k,0) for m in valid]
            ann[k] = sum(vals)/len(vals) if k in avg_k else sum(vals)
        ann['meses'] = len(valid)
        ann['revpar'] = ann.get('adr',0) * ann.get('occ_pct',0)
        out['years'][str(year)] = {
            'annual':  {k: round(float(v),2) for k,v in ann.items()},
            'monthly': {m: {k: round(float(v),2) for k,v in months[m].items()} for m in valid}
        }
    return out

def process_excel(buf):
    xl = pd.ExcelFile(buf)
    print(f"Sheets found: {xl.sheet_names}")
    hotels = {}

    # Sheet configs: name -> (hotel_name, er_month_row, er_year_row, hab_month_row, hab_year_row)
    SHEET_CONFIG = {
        'HJ RESISTENCIA': ('Howard Johnson La Ribera', 5, 6, None, None),
        'HJ CARILO':      ('Howard Johnson Carilo',   210, 211, 5, 6),
        'SOHO':           ('Soho Suites',              70, 71, 5, 6),
    }

    for sheet in xl.sheet_names:
        if sheet not in SHEET_CONFIG:
            print(f"  Skipping unknown sheet: {sheet}")
            continue
        hotel_name, emr, eyr, hmr, hyr = SHEET_CONFIG[sheet]
        print(f"  Processing {sheet} -> {hotel_name}")
        df = pd.read_excel(buf, sheet_name=sheet, header=None)
        key = hotel_name.replace('Howard Johnson ', 'HJ ').replace('Carilo','Carilo')
        hotels[key] = extract_hotel(df, hotel_name, emr, eyr, hmr, hyr)
        for y, yd in hotels[key]['years'].items():
            a = yd['annual']; vt = a['v_total']
            if vt:
                print(f"    {y} ({int(a['meses'])}m): Ventas={vt/1e6:.0f}M  GOP={a['gop']/vt*100:.1f}%")

    return hotels

# Ã¢ÂÂÃ¢ÂÂ HTML GENERATION Ã¢ÂÂÃ¢ÂÂ
def generate_html(hotels, logo_b64=None):
    hotels_js = json.dumps(hotels, ensure_ascii=False)
    logo_src = f"data:image/svg+xml;base64,{logo_b64}" if logo_b64 else ""

    # Read template
    template_path = 'er_template.html'
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    html = template.replace('__HOTELS_DATA__', hotels_js)
    html = html.replace('__LOGO_SRC__', logo_src)
    return html

# Ã¢ÂÂÃ¢ÂÂ GITHUB UPLOAD Ã¢ÂÂÃ¢ÂÂ
def upload_to_github(html_content, filename=OUTPUT_HTML):
    token = os.environ.get('GTH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    repo  = os.environ.get('GITHUB_REPOSITORY', 'GTHHotelero/gth-dashboard')

    api_url = f"https://api.github.com/repos/{repo}/contents/{filename}"
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # Get current SHA
    r = requests.get(api_url, headers=headers)
    sha = r.json().get('sha') if r.status_code == 200 else None

    content_b64 = base64.b64encode(html_content.encode('utf-8')).decode()
    payload = {
        'message': 'Auto-update E/R Dashboard',
        'content': content_b64,
        'branch': 'main'
    }
    if sha:
        payload['sha'] = sha

    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"Ã¢ÂÂ {filename} uploaded successfully")
    else:
        print(f"Ã¢ÂÂ Upload failed: {r.status_code} {r.text[:200]}")
        sys.exit(1)

# Ã¢ÂÂÃ¢ÂÂ MAIN Ã¢ÂÂÃ¢ÂÂ
if __name__ == '__main__':
    print("GTH E/R Dashboard Generator")
    print(f"Downloading Excel from Drive (file_id={FILE_ID})...")
    buf = download_excel(FILE_ID)

    print("Extracting hotel data...")
    hotels = process_excel(buf)

    # Load logo if available
    logo_b64 = None
    logo_path = 'logo-gth.b64'
    if os.path.exists(logo_path):
        with open(logo_path, 'r') as f:
            logo_b64 = f.read().strip()

    print("Generating HTML...")
    html = generate_html(hotels, logo_b64)

    print("Writing HTML to disk...")
    with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Done! {OUTPUT_HTML} written ({len(html):,} bytes)")
