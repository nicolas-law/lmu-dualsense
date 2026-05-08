"""
Telemetry dashboard: FastAPI web server.

Live view:     http://localhost:8080/
Session list:  http://localhost:8080/sessions
Lap analysis:  http://localhost:8080/laps/<id>
Lap compare:   http://localhost:8080/compare?a=<id>&b=<id>

Runs in a daemon thread alongside the DearPyGUI overlay.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from lmu_dualsense.feedback import AppState
from lmu_dualsense.telemetry.recorder import Recorder

logger = logging.getLogger(__name__)

_PORT = 8080


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(app_state: AppState, recorder: Recorder) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)

    # -- API ----------------------------------------------------------------

    @app.get("/api/live")
    def api_live() -> JSONResponse:
        tel = app_state.telemetry
        if tel is None:
            return JSONResponse({"active": False, "game": app_state.game})
        fg = min(tel.wheel_grip[0], tel.wheel_grip[1])
        abs_on = tel.abs_active or (
            tel.brake > 0.1 and fg < app_state.config.abs_grip_threshold
        )
        return JSONResponse({
            "active": True,
            "game": app_state.game,
            "track": tel.track_name,
            "vehicle": tel.vehicle_name,
            "lap": tel.lap_number,
            "lap_elapsed": round(tel.lap_elapsed, 2),
            "session_elapsed": round(tel.session_elapsed, 2),
            "speed_kmh": round(tel.speed_ms * 3.6, 1),
            "throttle": round(tel.throttle, 3),
            "brake": round(tel.brake, 3),
            "steering": round(tel.steering, 3),
            "gear": tel.gear,
            "rpm": round(tel.engine_rpm),
            "rpm_max": round(tel.engine_max_rpm),
            "fuel": round(tel.fuel, 2),
            "abs": abs_on,
            "grip": {
                "fl": round(tel.wheel_grip[0], 3),
                "fr": round(tel.wheel_grip[1], 3),
                "rl": round(tel.wheel_grip[2], 3),
                "rr": round(tel.wheel_grip[3], 3),
            },
            "wear": {
                "fl": round(tel.tire_wear[0], 4),
                "fr": round(tel.tire_wear[1], 4),
                "rl": round(tel.tire_wear[2], 4),
                "rr": round(tel.tire_wear[3], 4),
            },
        })

    @app.get("/api/sessions")
    def api_sessions() -> JSONResponse:
        with _db(recorder) as con:
            rows = con.execute(
                "SELECT id, track, vehicle, started_at, ended_at FROM sessions ORDER BY id DESC"
            ).fetchall()
        return JSONResponse([
            {"id": r[0], "track": r[1], "vehicle": r[2], "started_at": r[3], "ended_at": r[4]}
            for r in rows
        ])

    @app.get("/api/sessions/{sid}/laps")
    def api_session_laps(sid: int) -> JSONResponse:
        with _db(recorder) as con:
            rows = con.execute(
                "SELECT id, lap_number, lap_time_s FROM laps WHERE session_id=? ORDER BY lap_number",
                (sid,),
            ).fetchall()
        if not rows:
            raise HTTPException(404, "session not found")
        times = [r[2] for r in rows if r[2] is not None]
        best = min(times) if times else None
        return JSONResponse({
            "session_id": sid,
            "best_lap_s": best,
            "laps": [
                {"id": r[0], "lap_number": r[1], "lap_time_s": r[2]}
                for r in rows
            ],
        })

    @app.get("/api/laps/{lid}/samples")
    def api_lap_samples(lid: int) -> JSONResponse:
        with _db(recorder) as con:
            rows = con.execute(
                """SELECT lap_elapsed, speed_ms, throttle, brake, steering, gear, rpm,
                          grip_fl, grip_fr, grip_rl, grip_rr,
                          wear_fl, wear_fr, wear_rl, wear_rr,
                          pos_x, pos_z
                   FROM samples WHERE lap_id=? ORDER BY lap_elapsed""",
                (lid,),
            ).fetchall()
        if not rows:
            raise HTTPException(404, "lap not found")
        return JSONResponse({
            "lap_id": lid,
            "count": len(rows),
            "t":        [r[0] for r in rows],
            "speed":    [round(r[1] * 3.6, 1) for r in rows],
            "throttle": [round(r[2], 3) for r in rows],
            "brake":    [round(r[3], 3) for r in rows],
            "steering": [round(r[4], 3) for r in rows],
            "gear":     [r[5] for r in rows],
            "rpm":      [round(r[6]) for r in rows],
            "grip":     {"fl": [round(r[7],3) for r in rows], "fr": [round(r[8],3) for r in rows],
                         "rl": [round(r[9],3) for r in rows], "rr": [round(r[10],3) for r in rows]},
            "wear":     {"fl": [round(r[11],4) for r in rows], "fr": [round(r[12],4) for r in rows],
                         "rl": [round(r[13],4) for r in rows], "rr": [round(r[14],4) for r in rows]},
            "pos_x":    [round(r[15], 1) for r in rows],
            "pos_z":    [round(r[16], 1) for r in rows],
        })

    # -- Pages --------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def page_live() -> str:
        return _PAGE_LIVE

    @app.get("/sessions", response_class=HTMLResponse)
    def page_sessions() -> str:
        return _PAGE_SESSIONS

    @app.get("/laps/{lid}", response_class=HTMLResponse)
    def page_lap(lid: int) -> str:
        return _PAGE_LAP.replace("__LAP_ID__", str(lid))

    @app.get("/sessions/{sid}", response_class=HTMLResponse)
    def page_session_detail(sid: int) -> str:
        return _PAGE_SESSIONS_DETAIL

    @app.get("/compare", response_class=HTMLResponse)
    def page_compare(a: int, b: int) -> str:
        return _PAGE_COMPARE.replace("__LAP_A__", str(a)).replace("__LAP_B__", str(b))

    return app


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


@contextmanager
def _db(recorder: Recorder) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(recorder._path), check_same_thread=False)  # noqa: SLF001
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def start(app_state: AppState, recorder: Recorder, port: int = _PORT) -> uvicorn.Server:
    cfg = uvicorn.Config(
        create_app(app_state, recorder),
        host="0.0.0.0",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(cfg)
    t = threading.Thread(target=server.run, daemon=True, name="dashboard-server")
    t.start()
    logger.info("Dashboard available at http://localhost:%d  (all interfaces)", port)
    return server


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

_STYLE = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{font-family:monospace;background:#111;color:#ddd;margin:0;padding:16px}
  h1{color:#e8c840;margin-top:0}
  a{color:#6ab0f5;text-decoration:none} a:hover{text-decoration:underline}
  nav{margin-bottom:20px}
  nav a{margin-right:16px;font-size:14px}
  .card{background:#1e1e1e;border-radius:6px;padding:16px;margin-bottom:16px}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;color:#888;font-weight:normal;padding:4px 8px;border-bottom:1px solid #333}
  td{padding:4px 8px;border-bottom:1px solid #222}
  tr:hover td{background:#252525}
  .best{color:#6ef06e}
  .bar-wrap{background:#333;border-radius:3px;height:10px;overflow:hidden;margin-top:2px}
  .bar{height:10px;border-radius:3px;transition:width .15s}
  .thr{background:#4caf50} .brk{background:#e53935} .fuel{background:#1565c0}
  .val{font-size:22px;font-weight:bold}
  .label{font-size:11px;color:#888;margin-bottom:2px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}
  .grip-bar-wrap{height:6px;background:#333;border-radius:3px;overflow:hidden}
  .grip-bar{height:6px;border-radius:3px}
  canvas{max-width:100%}
  .abs-on{color:#ff5252;font-weight:bold}
  .abs-off{color:#666}
  #status{font-size:12px;color:#888;margin-bottom:8px}
</style>
"""

_NAV = '<nav><a href="/">⚡ Live</a><a href="/sessions">📋 Sessions</a></nav>'

# ── Live page ──────────────────────────────────────────────────────────────

_PAGE_LIVE = f"""<!DOCTYPE html><html><head>{_STYLE}<title>Live Telemetry</title></head><body>
{_NAV}
<h1>Live Telemetry</h1>
<div id="status">Connecting…</div>
<div class="grid2">
  <div class="card">
    <div class="label">SPEED</div>
    <div class="val" id="speed">–</div>
    <div style="color:#888;font-size:12px">km/h</div>
  </div>
  <div class="card">
    <div class="label">LAP</div>
    <div class="val" id="lap">–</div>
    <div style="color:#888;font-size:12px" id="lap_time">–</div>
  </div>
</div>
<div class="card">
  <div class="grid2">
    <div>
      <div class="label">THROTTLE</div>
      <div class="bar-wrap"><div class="bar thr" id="bar_thr" style="width:0%"></div></div>
      <div id="val_thr" style="font-size:12px;margin-top:2px">0%</div>
    </div>
    <div>
      <div class="label">BRAKE</div>
      <div class="bar-wrap"><div class="bar brk" id="bar_brk" style="width:0%"></div></div>
      <div id="val_brk" style="font-size:12px;margin-top:2px">0%</div>
    </div>
  </div>
  <div style="margin-top:10px;display:flex;gap:20px">
    <span><span style="color:#888">Gear </span><b id="gear">–</b></span>
    <span><span style="color:#888">RPM </span><b id="rpm">–</b></span>
    <span><span style="color:#888">Fuel </span><b id="fuel">–</b></span>
    <span><b id="abs_label" class="abs-off">ABS</b></span>
  </div>
</div>
<div class="card">
  <div class="label">GRIP</div>
  <div class="grid4">
    <div><div class="label">FL</div><div class="grip-bar-wrap"><div class="grip-bar" id="g_fl" style="background:#4caf50;width:100%"></div></div><span id="gv_fl" style="font-size:11px">–</span></div>
    <div><div class="label">FR</div><div class="grip-bar-wrap"><div class="grip-bar" id="g_fr" style="background:#4caf50;width:100%"></div></div><span id="gv_fr" style="font-size:11px">–</span></div>
    <div><div class="label">RL</div><div class="grip-bar-wrap"><div class="grip-bar" id="g_rl" style="background:#4caf50;width:100%"></div></div><span id="gv_rl" style="font-size:11px">–</span></div>
    <div><div class="label">RR</div><div class="grip-bar-wrap"><div class="grip-bar" id="g_rr" style="background:#4caf50;width:100%"></div></div><span id="gv_rr" style="font-size:11px">–</span></div>
  </div>
  <div style="margin-top:12px" class="label">TIRE WEAR</div>
  <div class="grid4">
    <div><div class="label">FL</div><span id="w_fl" style="font-size:11px">–</span></div>
    <div><div class="label">FR</div><span id="w_fr" style="font-size:11px">–</span></div>
    <div><div class="label">RL</div><span id="w_rl" style="font-size:11px">–</span></div>
    <div><div class="label">RR</div><span id="w_rr" style="font-size:11px">–</span></div>
  </div>
</div>
<div class="card">
  <div class="label">THROTTLE / BRAKE (last 45 s)</div>
  <canvas id="traceChart" height="100"></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const WINDOW = 45; // seconds of rolling trace
const ctx = document.getElementById('traceChart').getContext('2d');
const chart = new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: [],
    datasets: [
      {{ label: 'Throttle', data: [], borderColor: '#4caf50', backgroundColor: 'transparent',
         borderWidth: 1.5, pointRadius: 0, tension: 0 }},
      {{ label: 'Brake',    data: [], borderColor: '#e53935', backgroundColor: 'transparent',
         borderWidth: 1.5, pointRadius: 0, tension: 0 }},
    ]
  }},
  options: {{
    animation: false, responsive: true,
    scales: {{
      x: {{ display: false }},
      y: {{ min: 0, max: 1, ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }}
  }}
}});

let traceT = [], traceThr = [], traceBrk = [];

function gripColor(v) {{
  if (v > 0.7) return '#4caf50';
  if (v > 0.4) return '#ff9800';
  return '#e53935';
}}

function fmtTime(s) {{
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(3).padStart(6, '0');
  return m + ':' + sec;
}}

async function refresh() {{
  try {{
    const r = await fetch('/api/live');
    const d = await r.json();
    if (!d.active) {{
      document.getElementById('status').textContent = d.game + ' — waiting for session…';
      return;
    }}
    document.getElementById('status').textContent = d.game + ' • ' + d.track + ' • ' + d.vehicle;
    document.getElementById('speed').textContent = d.speed_kmh;
    document.getElementById('lap').textContent = 'Lap ' + d.lap;
    document.getElementById('lap_time').textContent = fmtTime(d.lap_elapsed);
    const tPct = (d.throttle * 100).toFixed(0) + '%';
    const bPct = (d.brake * 100).toFixed(0) + '%';
    document.getElementById('bar_thr').style.width = tPct;
    document.getElementById('bar_brk').style.width = bPct;
    document.getElementById('val_thr').textContent = tPct;
    document.getElementById('val_brk').textContent = bPct;
    document.getElementById('gear').textContent = d.gear <= 1 ? (d.gear == 0 ? 'R' : 'N') : (d.gear - 1);
    document.getElementById('rpm').textContent = d.rpm.toLocaleString();
    document.getElementById('fuel').textContent = d.fuel.toFixed(1) + ' L';
    const absEl = document.getElementById('abs_label');
    absEl.className = d.abs ? 'abs-on' : 'abs-off';
    absEl.textContent = d.abs ? 'ABS!' : 'ABS';
    for (const w of ['fl','fr','rl','rr']) {{
      const v = d.grip[w];
      document.getElementById('g_' + w).style.width = (v * 100) + '%';
      document.getElementById('g_' + w).style.background = gripColor(v);
      document.getElementById('gv_' + w).textContent = v.toFixed(2);
      document.getElementById('w_' + w).textContent = (d.wear[w] * 100).toFixed(1) + '%';
    }}
    // rolling trace
    traceT.push(d.lap_elapsed); traceThr.push(d.throttle); traceBrk.push(d.brake);
    const cutoff = d.lap_elapsed - WINDOW;
    while (traceT.length > 0 && traceT[0] < cutoff) {{
      traceT.shift(); traceThr.shift(); traceBrk.shift();
    }}
    chart.data.labels = traceT;
    chart.data.datasets[0].data = traceThr;
    chart.data.datasets[1].data = traceBrk;
    chart.update();
  }} catch(e) {{}}
}}

setInterval(refresh, 500);
refresh();
</script>
</body></html>"""

# ── Sessions page ──────────────────────────────────────────────────────────

_PAGE_SESSIONS = f"""<!DOCTYPE html><html><head>{_STYLE}<title>Sessions</title></head><body>
{_NAV}
<h1>Recorded Sessions</h1>
<div class="card">
  <table>
    <thead><tr><th>Track</th><th>Vehicle</th><th>Date</th><th>Laps</th><th>Best Lap</th><th></th></tr></thead>
    <tbody id="rows"><tr><td colspan="6" style="color:#555">Loading…</td></tr></tbody>
  </table>
</div>
<script>
function fmtTime(s) {{
  if (!s) return '–';
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(3).padStart(6,'0');
  return m + ':' + sec;
}}
async function load() {{
  const sessions = await (await fetch('/api/sessions')).json();
  const tbody = document.getElementById('rows');
  if (!sessions.length) {{ tbody.innerHTML = '<tr><td colspan="6" style="color:#555">No sessions recorded yet.</td></tr>'; return; }}
  const rows = await Promise.all(sessions.map(async s => {{
    const r = await fetch('/api/sessions/' + s.id + '/laps');
    const ldata = r.ok ? await r.json() : null;
    const lapCount = ldata ? ldata.laps.length : '–';
    const best = ldata ? fmtTime(ldata.best_lap_s) : '–';
    const date = s.started_at ? s.started_at.replace('T',' ').substring(0,16) : '–';
    return `<tr>
      <td>${{s.track || '–'}}</td>
      <td>${{s.vehicle || '–'}}</td>
      <td>${{date}}</td>
      <td>${{lapCount}}</td>
      <td class="best">${{best}}</td>
      <td><a href="/sessions/${{s.id}}">View →</a></td>
    </tr>`;
  }}));
  tbody.innerHTML = rows.join('');
}}
load();
</script>
</body></html>"""

# ── Session detail page ────────────────────────────────────────────────────

_PAGE_SESSIONS_DETAIL = f"""<!DOCTYPE html><html><head>{_STYLE}<title>Session</title></head><body>
{_NAV}
<h1 id="title">Session</h1>
<div class="card">
  <table>
    <thead><tr><th>#</th><th>Lap</th><th>Time</th><th>Δ Best</th><th></th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<script>
const sid = location.pathname.split('/').pop();
function fmtTime(s) {{
  if (!s) return '–';
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(3).padStart(6,'0');
  return m + ':' + sec;
}}
async function load() {{
  const r = await fetch('/api/sessions/' + sid + '/laps');
  if (!r.ok) {{ document.getElementById('rows').innerHTML = '<tr><td colspan="5">Not found</td></tr>'; return; }}
  const data = await r.json();
  const best = data.best_lap_s;
  document.getElementById('title').textContent = 'Session ' + sid + ' — ' + data.laps.length + ' laps';
  const rows = data.laps.map((l,i) => {{
    const isBest = l.lap_time_s && l.lap_time_s === best;
    const delta = (l.lap_time_s && best) ? '+' + (l.lap_time_s - best).toFixed(3) : '';
    const cls = isBest ? 'best' : '';
    return `<tr>
      <td class="${{cls}}">${{i+1}}</td>
      <td class="${{cls}}">Lap ${{l.lap_number}}</td>
      <td class="${{cls}}">${{fmtTime(l.lap_time_s)}}</td>
      <td style="color:#888">${{isBest ? '🏆' : delta}}</td>
      <td><a href="/laps/${{l.id}}">Trace →</a>
          <a href="/compare?a=${{l.id}}&b=${{data.laps[0]?.id}}" style="margin-left:8px">Compare →</a></td>
    </tr>`;
  }});
  document.getElementById('rows').innerHTML = rows.join('');
}}
load();
</script>
</body></html>"""

# ── Lap analysis page ──────────────────────────────────────────────────────

_PAGE_LAP = f"""<!DOCTYPE html><html><head>{_STYLE}<title>Lap __LAP_ID__</title></head><body>
{_NAV}
<h1 id="title">Lap __LAP_ID__</h1>
<div class="card"><div class="label">SPEED (km/h)</div><canvas id="cSpeed" height="80"></canvas></div>
<div class="card"><div class="label">THROTTLE / BRAKE</div><canvas id="cInputs" height="80"></canvas></div>
<div class="card"><div class="label">WHEEL GRIP</div><canvas id="cGrip" height="80"></canvas></div>
<div class="card"><div class="label">TRACK MAP  (colored by speed)</div><canvas id="cMap" height="300"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const LID = __LAP_ID__;
async function load() {{
  const d = await (await fetch('/api/laps/' + LID + '/samples')).json();
  if (!d.count) {{ document.getElementById('title').textContent = 'No data for lap ' + LID; return; }}

  const opts = (extra) => ({{
    animation: false, responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#ccc', boxWidth: 10 }} }} }},
    scales: {{ x: {{ display: false }}, y: {{ ...extra, ticks: {{ color: '#888' }}, grid: {{ color: '#222' }} }} }}
  }});

  new Chart(document.getElementById('cSpeed').getContext('2d'), {{
    type:'line', data: {{ labels: d.t,
      datasets: [{{ label:'Speed km/h', data: d.speed, borderColor:'#6ab0f5',
                    backgroundColor:'transparent', borderWidth:1.5, pointRadius:0, tension:0 }}] }},
    options: opts({{ min:0 }})
  }});

  new Chart(document.getElementById('cInputs').getContext('2d'), {{
    type:'line', data: {{ labels: d.t, datasets: [
      {{ label:'Throttle', data: d.throttle, borderColor:'#4caf50', backgroundColor:'transparent', borderWidth:1.5, pointRadius:0, tension:0 }},
      {{ label:'Brake',    data: d.brake,    borderColor:'#e53935', backgroundColor:'transparent', borderWidth:1.5, pointRadius:0, tension:0 }},
    ]}}, options: opts({{ min:0, max:1 }})
  }});

  new Chart(document.getElementById('cGrip').getContext('2d'), {{
    type:'line', data: {{ labels: d.t, datasets: [
      {{ label:'FL', data: d.grip.fl, borderColor:'#aaa', backgroundColor:'transparent', borderWidth:1, pointRadius:0, tension:0 }},
      {{ label:'FR', data: d.grip.fr, borderColor:'#888', backgroundColor:'transparent', borderWidth:1, pointRadius:0, tension:0 }},
      {{ label:'RL', data: d.grip.rl, borderColor:'#e8c840', backgroundColor:'transparent', borderWidth:1, pointRadius:0, tension:0 }},
      {{ label:'RR', data: d.grip.rr, borderColor:'#c8a000', backgroundColor:'transparent', borderWidth:1, pointRadius:0, tension:0 }},
    ]}}, options: opts({{ min:0, max:1 }})
  }});

  // Track map: pos_x / pos_z colored by speed
  const maxSpeed = Math.max(...d.speed);
  const colors = d.speed.map(s => {{
    const t = s / maxSpeed;
    const r = Math.round(255 * (1-t)), g = Math.round(200 * t), b = 50;
    return `rgb(${{r}},${{g}},${{b}})`;
  }});
  new Chart(document.getElementById('cMap').getContext('2d'), {{
    type:'scatter',
    data: {{ datasets: [{{
      data: d.pos_x.map((x,i) => ({{ x, y: d.pos_z[i] }})),
      pointBackgroundColor: colors, pointRadius: 2, pointHoverRadius: 3,
    }}]}},
    options: {{
      animation: false, responsive: true, aspectRatio: 1.5,
      plugins: {{ legend: {{ display: false }}, tooltip: {{
        callbacks: {{ label: (ctx) => d.speed[ctx.dataIndex] + ' km/h' }}
      }} }},
      scales: {{
        x: {{ ticks: {{ color:'#888' }}, grid: {{ color:'#222' }} }},
        y: {{ ticks: {{ color:'#888' }}, grid: {{ color:'#222' }} }}
      }}
    }}
  }});
}}
load();
</script>
</body></html>"""

# ── Compare page ───────────────────────────────────────────────────────────

_PAGE_COMPARE = f"""<!DOCTYPE html><html><head>{_STYLE}<title>Compare Laps</title></head><body>
{_NAV}
<h1>Lap Comparison</h1>
<div class="card"><div class="label">SPEED (km/h)</div><canvas id="cSpeed" height="80"></canvas></div>
<div class="card"><div class="label">BRAKE</div><canvas id="cBrake" height="80"></canvas></div>
<div class="card"><div class="label">THROTTLE</div><canvas id="cThrottle" height="80"></canvas></div>
<div class="card"><div class="label">GRIP FL+RL (left side)</div><canvas id="cGripL" height="70"></canvas></div>
<div class="card"><div class="label">GRIP FR+RR (right side)</div><canvas id="cGripR" height="70"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const LA = __LAP_A__, LB = __LAP_B__;
async function load() {{
  const [da, db] = await Promise.all([
    fetch('/api/laps/' + LA + '/samples').then(r => r.json()),
    fetch('/api/laps/' + LB + '/samples').then(r => r.json()),
  ]);

  function mkChart(id, datasets, yOpts={{}}) {{
    new Chart(document.getElementById(id).getContext('2d'), {{
      type:'line', data: {{ datasets }},
      options: {{
        animation: false, responsive: true,
        plugins: {{ legend: {{ labels: {{ color:'#ccc', boxWidth:10 }} }} }},
        scales: {{
          x: {{ type:'linear', display:true, ticks:{{ color:'#888', maxTicksLimit:10 }}, grid:{{ color:'#222' }},
               title:{{ display:true, text:'lap time (s)', color:'#666' }} }},
          y: {{ ...yOpts, ticks:{{ color:'#888' }}, grid:{{ color:'#222' }} }}
        }}
      }}
    }});
  }}

  function ds(label, t, vals, color) {{
    return {{ label, data: t.map((x,i) => ({{x, y:vals[i]}})),
              borderColor: color, backgroundColor:'transparent',
              borderWidth:1.5, pointRadius:0, tension:0 }};
  }}

  mkChart('cSpeed',   [ds('Lap '+LA, da.t, da.speed,    '#6ab0f5'), ds('Lap '+LB, db.t, db.speed,    '#f0a060')]);
  mkChart('cBrake',   [ds('Lap '+LA, da.t, da.brake,    '#e53935'), ds('Lap '+LB, db.t, db.brake,    '#ff8a80')], {{min:0,max:1}});
  mkChart('cThrottle',[ds('Lap '+LA, da.t, da.throttle, '#4caf50'), ds('Lap '+LB, db.t, db.throttle, '#a5d6a7')], {{min:0,max:1}});
  const gripLA = da.t.map((_,i) => Math.min(da.grip.fl[i], da.grip.rl[i]));
  const gripLB = db.t.map((_,i) => Math.min(db.grip.fl[i], db.grip.rl[i]));
  const gripRA = da.t.map((_,i) => Math.min(da.grip.fr[i], da.grip.rr[i]));
  const gripRB = db.t.map((_,i) => Math.min(db.grip.fr[i], db.grip.rr[i]));
  mkChart('cGripL', [ds('Lap '+LA, da.t, gripLA, '#e0e0e0'), ds('Lap '+LB, db.t, gripLB, '#9e9e9e')], {{min:0,max:1}});
  mkChart('cGripR', [ds('Lap '+LA, da.t, gripRA, '#e0e0e0'), ds('Lap '+LB, db.t, gripRB, '#9e9e9e')], {{min:0,max:1}});
}}
load();
</script>
</body></html>"""
