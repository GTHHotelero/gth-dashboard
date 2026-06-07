#!/usr/bin/env python3
"""
GTH Dashboard Generator — GitHub Actions
Lee datos.json del repo y publica index.html + ejecutivo.html via API
"""
import os, sys, json, base64, datetime, urllib.request, urllib.error, csv, io
from collections import defaultdict

REPO   = "GTHHotelero/gth-dashboard"
BRANCH = "main"

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
    body = {"message": f"GTH Dashboard · {datetime.date.today().strftime('%d/%m/%Y')} · auto", "content": base64.b64encode(content_bytes).decode(), "branch": BRANCH}
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

def build_dashboard(csv_data, logo_b64):
    """Genera el HTML del reporte diario K007"""
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

    # Leer el template guardado en el repo
    with open("template_dashboard.html") as f_t:
        html = f_t.read()

    def replace_const(html, name, value):
        start = html.find(f'const {name} = ')
        end = html.find(';\n', start) + 2
        return html[:start] + f'const {name} = {value};\n' + html[end:]

    html = replace_const(html, 'DB', DB_JSON)
    html = replace_const(html, 'FECHAS', FECHAS_JSON)
    html = replace_const(html, 'HOTELES', HOTELES_JSON)
    # Actualizar logo
    html = html.replace('__LOGO_B64__', logo_b64)
    return html

def build_ejecutivo(csv_data, logo_b64):
    """Genera el HTML del informe ejecutivo"""
    with open("template_ejecutivo.html") as f_t:
        html = f_t.read()
    html = html.replace('__LOGO_B64__', logo_b64)
    # Actualizar datos en el template ejecutivo
    # (el template tiene __CSV_DATA__ como placeholder)
    html = html.replace('__CSV_DATA__', csv_data.replace('`','\\`').replace('\\','\\\\'))
    return html

if __name__ == "__main__":
    print("=== GTH Dashboard Generator ===", flush=True)

    logo_b64 = os.environ.get("LOGO_B64", "")
    gh_token = os.environ.get("GH_TOKEN", "")
    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)

    # Leer datos.csv del repo
    print("Leyendo datos.csv desde GitHub...", flush=True)
    try:
        csv_data, _ = github_get("datos.csv", gh_token)
        lineas = csv_data.strip().split('\n')
        print(f"CSV OK: {len(lineas)-1} registros", flush=True)
    except Exception as e:
        print(f"Error leyendo datos.csv: {e}", flush=True)
        sys.exit(1)

    # Generar HTMLs
    print("Generando dashboard K007...", flush=True)
    html_dash = build_dashboard(csv_data, logo_b64)
    print(f"Dashboard: {len(html_dash):,} chars", flush=True)

    print("Generando informe ejecutivo...", flush=True)
    html_ejec = build_ejecutivo(csv_data, logo_b64)
    print(f"Ejecutivo: {len(html_ejec):,} chars", flush=True)

    # Subir a GitHub
    print("Subiendo a GitHub...", flush=True)
    github_put("index.html",     html_dash.encode("utf-8"), gh_token, sha=get_sha("index.html", gh_token))
    github_put("ejecutivo.html", html_ejec.encode("utf-8"), gh_token, sha=get_sha("ejecutivo.html", gh_token))

    print("=== DONE ===", flush=True)
