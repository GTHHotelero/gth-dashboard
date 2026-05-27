#!/usr/bin/env python3
"""
GTH Dashboard Generator - GitHub Actions
Lee datos.json desde Google Drive (generado por Claude)
y publica index.html en GitHub via API
"""
import os, sys, json, base64, datetime, urllib.request, urllib.error
from pathlib import Path

DATOS_JSON_ID = "19JTaCK787E9qFsTiLBmd-cz27xd3Q3nI"
LOGO_B64_FALLBACK = ""  # se toma de secret LOGO_B64

def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    sa_json = os.environ["GDRIVE_SERVICE_ACCOUNT_JSON"]
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)

def read_file_text(service, file_id):
    import io
    from googleapiclient.http import MediaIoBaseDownload
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8")

def github_put(path, content_bytes, token, repo="GTHHotelero/gth-dashboard", branch="main"):
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "GTH-Dashboard"
    }
    sha = None
    req = urllib.request.Request(url + f"?ref={branch}", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read()).get("sha")
    except:
        pass
    body = {
        "message": f"Dashboard GTH · {datetime.date.today().strftime('%d/%m/%Y')} · automático",
        "content": base64.b64encode(content_bytes).decode(),
        "branch": branch
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            print(f"  ✅ {path}: {resp['commit']['sha'][:8]}", flush=True)
            return True
    except urllib.error.HTTPError as e:
        print(f"  ❌ {path}: {e.code} {e.read().decode()[:200]}", flush=True)
        return False

def generate_html(db, logo_b64):
    db_json = json.dumps(db, ensure_ascii=False, default=lambda x: None)
    ultima = db["ultima_fecha"]
    fd = ultima.split("-")
    fecha_display = f"{fd[2]}/{fd[1]}/{fd[0]}"
    fechas_opts = ""
    for f in sorted(db["fechas"], reverse=True):
        ffd = f.split("-")
        ffd_str = f"{ffd[2]}/{ffd[1]}/{ffd[0]}"
        fechas_opts += f'<option value="{f}"{" selected" if f==ultima else ""}>{ffd_str}</option>\n'

    CSS = """
:root{--gold:#9E8E5A;--gold-l:#C4B07A;--gold-bg:rgba(158,142,90,0.12);--grey:#787878;--grey-bg:#F4F3F0;--grey-d:#3A3A3A;--bg:#F9F8F5;--card:#fff;--plr:#378ADD;--hjc:#1D9E75;--soho:#D85A30;--red:#C0392B;--green:#1D9E75;--border:#E8E5DE;--sh:0 2px 12px rgba(0,0,0,0.07)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--grey-d)}
.topbar{background:#fff;border-bottom:3px solid var(--gold);padding:0 28px;display:flex;align-items:center;justify-content:space-between;height:64px;position:sticky;top:0;z-index:100;box-shadow:var(--sh)}
.topbar-logo{display:flex;align-items:center;gap:14px}
.topbar-logo img{height:38px;width:auto}
.topbar-title{font-family:'Playfair Display',serif;font-size:18px;font-weight:600;color:var(--grey-d)}
.topbar-meta{font-size:12px;color:var(--grey);text-align:right;line-height:1.5}
.topbar-meta strong{color:var(--gold);font-weight:600}
.date-select{font-family:'DM Sans',sans-serif;font-size:13px;font-weight:500;color:var(--grey-d);background:#fff;border:1px solid #e8e5de;border-radius:6px;padding:6px 12px;cursor:pointer}
.alerts-bar{padding:10px 28px;display:flex;gap:10px;flex-wrap:wrap;background:#fff;border-bottom:1px solid #eee}
.alert-chip{display:flex;align-items:center;gap:6px;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;border-left:4px solid}
.alert-critico{background:#fdf0f0;border-left-color:var(--red);color:var(--red)}
.alert-alerta{background:#fdf8ee;border-left-color:var(--gold);color:#7a6930}
.alert-ok{background:#f0faf5;border-left-color:var(--green);color:#156047}
.tabs-wrap{background:#fff;border-bottom:1px solid #eee;padding:0 28px;display:flex}
.tab-btn{padding:14px 22px;border:none;background:none;font-family:'DM Sans',sans-serif;font-size:13px;font-weight:500;color:var(--grey);cursor:pointer;border-bottom:3px solid transparent;transition:all 0.2s}
.tab-btn:hover{color:var(--gold)}
.tab-btn.active{color:var(--gold);border-bottom-color:var(--gold);font-weight:600}
.main{padding:24px 28px;max-width:1280px;margin:0 auto}
.tab-panel{display:none}
.tab-panel.active{display:block}
.section-title{font-family:'Playfair Display',serif;font-size:15px;font-weight:600;color:var(--grey-d);margin-bottom:16px;padding-bottom:6px;border-bottom:1px solid #e8e5de;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--gold);display:inline-block}
.hotel-section{margin-bottom:32px}
.hotel-header{display:flex;align-items:center;gap:12px;margin-bottom:16px;padding:12px 18px;border-radius:8px;color:#fff}
.hotel-header h2{font-family:'Playfair Display',serif;font-size:16px;font-weight:600}
.hotel-meta{font-size:12px;opacity:.85;margin-left:auto}
.hotel-plr{background:linear-gradient(135deg,#378ADD,#2166b5)}
.hotel-hjc{background:linear-gradient(135deg,#1D9E75,#148054)}
.hotel-soho{background:linear-gradient(135deg,#D85A30,#b84320)}
.hotel-gth{background:linear-gradient(135deg,#9E8E5A,#7a6a3a)}
.hotel-kpi-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.hotel-kpi-card{background:#fff;border-radius:8px;padding:14px 16px;box-shadow:var(--sh);border-left:4px solid var(--gold)}
.hotel-kpi-card.dia{border-left-color:var(--gold)}
.hotel-kpi-card.mes{border-left-color:var(--grey)}
.hotel-kpi-label{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--grey);margin-bottom:4px;display:flex;align-items:center;gap:6px}
.badge-dia{background:rgba(158,142,90,0.15);color:var(--gold);font-size:9px;padding:1px 5px;border-radius:4px;font-weight:700}
.badge-mes{background:#f0f0f0;color:var(--grey);font-size:9px;padding:1px 5px;border-radius:4px;font-weight:700}
.hotel-kpi-value{font-family:'Playfair Display',serif;font-size:20px;font-weight:700;margin-bottom:6px}
.kpi-comparatives{display:flex;gap:8px;flex-wrap:wrap}
.chip{font-size:10px;font-weight:600;padding:2px 7px;border-radius:10px}
.chip-ma{background:#f0f0f0;color:#555}
.chip-aa{background:#f5f0e8;color:#7a6930}
.chip-up{color:var(--green)}
.chip-down{color:var(--red)}
.chip-neutral{color:var(--grey)}
.progress-bar{height:4px;background:#f0ede6;border-radius:2px;margin-top:8px;overflow:hidden}
.progress-fill{height:100%;border-radius:2px;background:var(--gold)}
.hotel-revenue-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.rev-mini{background:var(--grey-bg);border-radius:6px;padding:10px 12px;text-align:center}
.rev-mini-label{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--grey);margin-bottom:3px}
.rev-mini-value{font-size:14px;font-weight:700;color:var(--grey-d)}
.seg-table-wrap{overflow-x:auto;margin-bottom:24px}
.seg-table{width:100%;border-collapse:collapse;font-size:12px;background:#fff;border-radius:8px;overflow:hidden;box-shadow:var(--sh)}
.seg-table th{background:var(--grey-d);color:#fff;padding:10px 12px;text-align:right;font-size:11px;font-weight:600}
.seg-table th:first-child{text-align:left}
.seg-table td{padding:9px 12px;border-bottom:1px solid #f0ede6;text-align:right}
.seg-table td:first-child{text-align:left;font-weight:500}
.seg-table tr:hover{background:#faf9f6}
.var-pos{color:var(--green);font-weight:600}
.var-neg{color:var(--red);font-weight:600}
.charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.chart-card{background:#fff;border-radius:10px;padding:20px;box-shadow:var(--sh)}
.chart-title{font-size:13px;font-weight:600;color:var(--grey-d);margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #f0ede6}
.footer{margin-top:40px;padding:16px 28px;background:var(--grey-d);color:rgba(255,255,255,.6);font-size:11px;text-align:center}
.footer strong{color:var(--gold)}
@media(max-width:768px){.main{padding:16px}.charts-grid{grid-template-columns:1fr}.hotel-revenue-row{grid-template-columns:1fr 1fr}.hotel-kpi-grid{grid-template-columns:1fr}.tabs-wrap{overflow-x:auto}.tab-btn{padding:12px 14px;font-size:12px;white-space:nowrap}}
"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GTH · Dashboard Hotelero · {fecha_display}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-logo">
    <img src="data:image/jpeg;base64,{logo_b64}" alt="GTH Logo">
    <div>
      <div class="topbar-title">Dashboard Hotelero</div>
      <div style="font-size:11px;color:var(--grey)">Reporte del día · K007</div>
    </div>
  </div>
  <div class="topbar-meta"><strong id="fecha-header">{fecha_display}</strong><br>3 propiedades · 267 habitaciones</div>
</div>
<div style="background:#fff;border-bottom:1px solid #eee;padding:8px 28px;display:flex;align-items:center;gap:12px">
  <span style="font-size:11px;color:var(--grey);font-weight:600;letter-spacing:.5px">VER FECHA:</span>
  <select class="date-select" id="date-select" onchange="renderAll(this.value)">
    {fechas_opts}
  </select>
</div>
<div class="alerts-bar" id="alerts-bar"></div>
<div class="tabs-wrap">
  <button class="tab-btn active" onclick="showTab('resumen',event)">📊 Resumen</button>
  <button class="tab-btn" onclick="showTab('hotel',event)">🏨 Por Hotel</button>
  <button class="tab-btn" onclick="showTab('segmentos',event)">📋 Segmentos</button>
  <button class="tab-btn" onclick="showTab('graficos',event)">📈 Gráficos</button>
</div>
<div class="main">
  <div id="tab-resumen" class="tab-panel active">
    <div class="section-title"><span class="dot"></span>Cadena GTH — Consolidado</div>
    <div id="resumen-cadena"></div>
  </div>
  <div id="tab-hotel" class="tab-panel"><div id="hotel-sections"></div></div>
  <div id="tab-segmentos" class="tab-panel">
    <div class="seg-table-wrap">
      <table class="seg-table">
        <thead><tr>
          <th style="text-align:left">Segmento</th>
          <th>Mes actual</th><th>Mes ant.</th><th>Var %</th><th>Año ant.</th><th>Var AA%</th>
        </tr></thead>
        <tbody id="seg-tbody"></tbody>
      </table>
    </div>
    <div class="chart-card" style="margin-top:16px">
      <div class="chart-title">Segmentos por hotel — Mes actual</div>
      <canvas id="chartSeg" height="110"></canvas>
    </div>
  </div>
  <div id="tab-graficos" class="tab-panel">
    <div class="charts-grid">
      <div class="chart-card"><div class="chart-title">Ocupación — Día / Mes / Mes Ant.</div><canvas id="chartOc" height="160"></canvas></div>
      <div class="chart-card"><div class="chart-title">ADR — Mes vs Mes Ant. (miles $)</div><canvas id="chartADR" height="160"></canvas></div>
      <div class="chart-card"><div class="chart-title">RevPAR — Mes vs Mes Ant. (miles $)</div><canvas id="chartRP" height="160"></canvas></div>
      <div class="chart-card"><div class="chart-title">Revenue — Rooms / A&B / Extras (mill. $)</div><canvas id="chartRev" height="160"></canvas></div>
    </div>
  </div>
</div>
<div class="footer">Gestión y Talentos Hoteleros · <strong>GTH</strong> · Manager Report K007 · gthhotelero.github.io/gth-dashboard</div>
<script>
const DB={db_json};
const HOTELES=[{{nombre:"HJ Plaza La Ribera",color:"#378ADD",cls:"plr"}},{{nombre:"Howard Johnson Caril\\u00f3",color:"#1D9E75",cls:"hjc"}},{{nombre:"Soho Park",color:"#D85A30",cls:"soho"}}];
const $=id=>document.getElementById(id);
const fp=v=>v?v.toFixed(1)+"%":"—";
const fm=v=>v?"$ "+(v/1e6).toFixed(1)+"M":"—";
const fp2=v=>v?"$ "+Math.round(v).toLocaleString("es-AR"):"—";
const gd=(f,h)=>DB.datos[f]&&DB.datos[f][h];
function chipMA(a,ma,t){{if(!ma)return'<span class="chip chip-ma">MA <span class="chip-neutral">—</span></span>';const d=a-ma,p=(d/Math.abs(ma)*100).toFixed(1),ar=d>=0?"↑":"↓",cl=d>=0?"chip-up":"chip-down";return`<span class="chip chip-ma">MA <span class="${{cl}}">${{ar}} ${{t==="pct"?Math.abs(d).toFixed(1)+"pp":Math.abs(p)+"%"}}</span></span>`;}}
function chipAA(a,aa,t){{if(!aa)return'<span class="chip chip-aa">AA <span class="chip-neutral">s/d</span></span>';const d=a-aa,p=(d/Math.abs(aa)*100).toFixed(1),ar=d>=0?"↑":"↓",cl=d>=0?"chip-up":"chip-down";return`<span class="chip chip-aa">AA <span class="${{cl}}">${{ar}} ${{t==="pct"?Math.abs(d).toFixed(1)+"pp":Math.abs(p)+"%"}}</span></span>`;}}
function vStr(a,b){{if(!b)return'<span style="color:#999">—</span>';const v=((a-b)/Math.abs(b)*100).toFixed(1);return`<span class="${{v>=0?"var-pos":"var-neg"}}">${{v>=0?"+":""}}${{v}}%</span>`;}}
function kpiPair(label,vd,vdaa,vm,vmma,vmaa,tipo,color){{const barD=tipo==="pct"?`<div class="progress-bar"><div class="progress-fill" style="width:${{Math.min(vd||0,100)}}%;background:${{color}}"></div></div>`:"";const barM=tipo==="pct"?`<div class="progress-bar"><div class="progress-fill" style="width:${{Math.min(vm||0,100)}}%;background:${{color}}40"></div></div>`:"";return`<div class="hotel-kpi-card dia"><div class="hotel-kpi-label">${{label}} <span class="badge-dia">DÍA</span></div><div class="hotel-kpi-value" style="color:${{color}}">${{tipo==="pct"?fp(vd):fp2(vd)}}</div><div class="kpi-comparatives">${{chipMA(vd,null,tipo)}} ${{chipAA(vd,vdaa,tipo)}}</div>${{barD}}</div><div class="hotel-kpi-card mes"><div class="hotel-kpi-label">${{label}} <span class="badge-mes">MES</span></div><div class="hotel-kpi-value">${{tipo==="pct"?fp(vm):fp2(vm)}}</div><div class="kpi-comparatives">${{chipMA(vm,vmma,tipo)}} ${{chipAA(vm,vmaa,tipo)}}</div>${{barM}}</div>`;}}
function bloqueHotel(d,cls,color,esCadena){{return`<div class="hotel-section"><div class="hotel-header ${{esCadena?"hotel-gth":"hotel-"+cls}}"><div><div style="font-size:11px;opacity:.85;margin-bottom:2px">${{d.hab}} habitaciones</div><h2>${{d.hotel}}</h2></div><div class="hotel-meta">Manager: ${{d.manager}} | Llegadas: ${{d.llegadas_dia||0}} | Salidas: ${{d.salidas_dia||0}}</div></div><div class="hotel-kpi-grid">${{kpiPair("Tarifa Prom. (ADR)",d.adr_dia,d.adr_dia_aa,d.adr_mes,d.adr_mes_ma,d.adr_mes_aa,"val",color)}}${{kpiPair("Ocupación",d.ocup_dia,d.ocup_dia_aa,d.ocup_mes,d.ocup_mes_ma,d.ocup_mes_aa,"pct",color)}}${{kpiPair("RevPAR",d.revpar_dia,d.revpar_dia_aa,d.revpar_mes,d.revpar_mes_ma,d.revpar_mes_aa,"val",color)}}</div><div class="hotel-revenue-row"><div class="rev-mini"><div class="rev-mini-label">Revenue Mes</div><div class="rev-mini-value">${{fm(d.rev_hotel_mes)}}</div></div><div class="rev-mini"><div class="rev-mini-label">Rooms Mes</div><div class="rev-mini-value">${{fm(d.rev_rooms_mes)}}</div></div><div class="rev-mini"><div class="rev-mini-label">A&B Mes</div><div class="rev-mini-value">${{fm(d.rev_aabb_mes)}}</div></div><div class="rev-mini"><div class="rev-mini-label">Llegadas Día</div><div class="rev-mini-value">${{d.llegadas_dia||0}}</div></div></div></div>`;}}
function renderAlertas(fecha){{$("alerts-bar").innerHTML=HOTELES.map(h=>{{const d=gd(fecha,h.nombre);if(!d)return"";const oc=d.ocup_dia||0;if(oc<20)return`<div class="alert-chip alert-critico">🔴 CRÍTICO · ${{h.nombre}}: Ocup. ${{fp(oc)}}</div>`;if(oc<40)return`<div class="alert-chip alert-alerta">⚠️ ALERTA · ${{h.nombre}}: Ocup. ${{fp(oc)}}</div>`;return`<div class="alert-chip alert-ok">✅ ${{h.nombre}}: Ocup. ${{fp(oc)}}</div>`;  }}).join("");}}
function renderResumen(fecha){{const ds=HOTELES.map(h=>gd(fecha,h.nombre)).filter(Boolean);if(!ds.length)return;const avg=k=>ds.reduce((s,d)=>s+(d[k]||0),0)/ds.length,sum=k=>ds.reduce((s,d)=>s+(d[k]||0),0);const c={{hab:267,hotel:"Cadena GTH",manager:"Promedio 3 hoteles",llegadas_dia:sum("llegadas_dia"),salidas_dia:sum("salidas_dia"),adr_dia:avg("adr_dia"),adr_dia_aa:avg("adr_dia_aa"),adr_mes:avg("adr_mes"),adr_mes_ma:avg("adr_mes_ma"),adr_mes_aa:avg("adr_mes_aa"),ocup_dia:avg("ocup_dia"),ocup_dia_aa:avg("ocup_dia_aa"),ocup_mes:avg("ocup_mes"),ocup_mes_ma:avg("ocup_mes_ma"),ocup_mes_aa:avg("ocup_mes_aa"),revpar_dia:avg("revpar_dia"),revpar_dia_aa:avg("revpar_dia_aa"),revpar_mes:avg("revpar_mes"),revpar_mes_ma:avg("revpar_mes_ma"),revpar_mes_aa:avg("revpar_mes_aa"),rev_hotel_mes:sum("rev_hotel_mes"),rev_rooms_mes:sum("rev_rooms_mes"),rev_aabb_mes:sum("rev_aabb_mes")}};$("resumen-cadena").innerHTML=bloqueHotel(c,"gth","#9E8E5A",true);}}
function renderHoteles(fecha){{$("hotel-sections").innerHTML=HOTELES.map(h=>{{const d=gd(fecha,h.nombre);if(!d)return"";return bloqueHotel(d,h.cls,h.color,false);}}).join("");}}
const SKS=["seg_individual","seg_corporativa","seg_otas","seg_grupos","seg_houseuse","seg_otras"];
const SMA=["seg_ind_ma","seg_corp_ma","seg_otas_ma","seg_grupos_ma","seg_houseuse_ma","seg_otras_ma"];
const SNS=["Individual / Rack","Corporativa","OTAs","Grupos","House Use","Otras"];
function renderSeg(fecha){{let rows="";HOTELES.forEach(h=>{{const d=gd(fecha,h.nombre);if(!d)return;rows+=`<tr><td colspan="6" style="color:${{h.color}};padding:9px 12px;background:#f5f3ee;font-weight:700;border-top:2px solid #e8e5de">● ${{h.nombre}}</td></tr>`;SKS.forEach((k,i)=>{{const v=d[k]||0,ma=d[SMA[i]];rows+=`<tr><td>${{SNS[i]}}</td><td>${{v}}</td><td>${{ma!=null?ma:"—"}}</td><td>${{ma!=null?vStr(v,ma):"—"}}</td><td>—</td><td>—</td></tr>`;}});}});$("seg-tbody").innerHTML=rows;const el=$("chartSeg");if(el._chart)el._chart.destroy();el._chart=new Chart(el,{{type:"bar",data:{{labels:SNS,datasets:HOTELES.filter(h=>gd(fecha,h.nombre)).map(h=>{{const d=gd(fecha,h.nombre);return{{label:h.nombre.replace("Howard Johnson ","HJ "),backgroundColor:h.color+"CC",data:SKS.map(k=>d[k]||0)}};}})}},options:{{responsive:true,plugins:{{legend:{{labels:{{font:{{family:"DM Sans"}}}}}}}},scales:{{x:{{ticks:{{font:{{family:"DM Sans",size:11}}}}}},y:{{ticks:{{font:{{family:"DM Sans",size:11}}}}}}}}}}}});}}
let CO={{}};
function renderGraficos(fecha){{Object.values(CO).forEach(c=>c&&c.destroy());CO={{}};const hds=HOTELES.map(h=>{{...h,d:gd(fecha,h.nombre)}});const lb=hds.map(h=>h.nombre.replace("Howard Johnson ","HJ "));const op={{responsive:true,plugins:{{legend:{{labels:{{font:{{family:"DM Sans",size:11}}}}}}}},scales:{{x:{{ticks:{{font:{{family:"DM Sans",size:11}}}}}},y:{{ticks:{{font:{{family:"DM Sans",size:11}}}}}}}}}};const oc=$("chartOc");if(oc)CO.oc=new Chart(oc,{{type:"bar",data:{{labels:lb,datasets:[{{label:"Día",backgroundColor:hds.map(h=>h.color+"EE"),data:hds.map(h=>h.d?h.d.ocup_dia||0:0)}},{{label:"Mes",backgroundColor:hds.map(h=>h.color+"77"),data:hds.map(h=>h.d?h.d.ocup_mes||0:0)}},{{label:"Mes Ant.",type:"line",borderColor:"#9E8E5A",pointBackgroundColor:"#9E8E5A",data:hds.map(h=>h.d?h.d.ocup_mes_ma||0:0),tension:.3}}]}},options:{{...op,scales:{{...op.scales,y:{{...op.scales.y,max:100}}}}}}}});const adr=$("chartADR");if(adr)CO.adr=new Chart(adr,{{type:"bar",data:{{labels:lb,datasets:[{{label:"ADR Mes",backgroundColor:hds.map(h=>h.color+"EE"),data:hds.map(h=>h.d?((h.d.adr_mes||0)/1000).toFixed(1):0)}},{{label:"ADR Mes Ant.",backgroundColor:hds.map(h=>h.color+"55"),data:hds.map(h=>h.d?((h.d.adr_mes_ma||0)/1000).toFixed(1):0)}}]}},options:op}});const rp=$("chartRP");if(rp)CO.rp=new Chart(rp,{{type:"bar",data:{{labels:lb,datasets:[{{label:"RevPAR Mes",backgroundColor:hds.map(h=>h.color+"EE"),data:hds.map(h=>h.d?((h.d.revpar_mes||0)/1000).toFixed(1):0)}},{{label:"RevPAR Mes Ant.",backgroundColor:hds.map(h=>h.color+"55"),data:hds.map(h=>h.d?((h.d.revpar_mes_ma||0)/1000).toFixed(1):0)}}]}},options:op}});const rv=$("chartRev");if(rv)CO.rv=new Chart(rv,{{type:"bar",data:{{labels:lb,datasets:[{{label:"Rooms",backgroundColor:"#378ADD99",data:hds.map(h=>h.d?((h.d.rev_rooms_mes||0)/1e6).toFixed(1):0)}},{{label:"A&B",backgroundColor:"#1D9E7599",data:hds.map(h=>h.d?((h.d.rev_aabb_mes||0)/1e6).toFixed(1):0)}},{{label:"Extras",backgroundColor:"#D85A3099",data:hds.map(h=>h.d?((h.d.rev_extras_mes||0)/1e6).toFixed(1):0)}}]}},options:{{...op,scales:{{...op.scales,x:{{...op.scales.x,stacked:true}},y:{{...op.scales.y,stacked:true}}}}}}}});}}
let fechaActual=DB.ultima_fecha;
function renderAll(fecha){{fechaActual=fecha;const fd=fecha.split("-");$("fecha-header").textContent=`${{fd[2]}}/${{fd[1]}}/${{fd[0]}}`;renderAlertas(fecha);renderResumen(fecha);renderHoteles(fecha);renderSeg(fecha);if($("tab-graficos").classList.contains("active"))renderGraficos(fecha);}}
function showTab(name,event){{document.querySelectorAll(".tab-panel").forEach(p=>p.classList.remove("active"));document.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));$("tab-"+name).classList.add("active");if(event)event.target.classList.add("active");if(name==="graficos")renderGraficos(fechaActual);}}
renderAll(DB.ultima_fecha);
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("=== GTH Dashboard Generator ===", flush=True)

    logo_b64 = os.environ.get("LOGO_B64", "")
    print(f"Logo: {'OK' if logo_b64 else 'sin logo'}", flush=True)

    print("Leyendo datos.json desde Drive...", flush=True)
    service = get_drive_service()
    datos_text = read_file_text(service, DATOS_JSON_ID)
    db = json.loads(datos_text)
    print(f"DB OK: {len(db['fechas'])} fechas, ultima: {db['ultima_fecha']}", flush=True)

    print("Generando HTML...", flush=True)
    html = generate_html(db, logo_b64)
    print(f"HTML: {len(html):,} chars", flush=True)

    gh_token = os.environ.get("GH_TOKEN")
    if gh_token:
        print("Subiendo a GitHub...", flush=True)
        github_put("index.html", html.encode("utf-8"), gh_token)
    else:
        print("Sin GH_TOKEN", flush=True)

    print("=== DONE ===", flush=True)
