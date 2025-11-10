import sqlite3
from flask import Flask, jsonify, render_template_string, request

DB = "commute.db"
app = Flask(__name__)

def q(sql, args=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall()
    con.close()
    return rows

TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Commute Monitor</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    select, button { padding: 6px 10px; font-size: 14px; }
    #chart { max-width: 1000px; }
  </style>
</head>
<body>
  <h2>Estimated Travel Time</h2>
  <div class="row">
    <label>Route:</label>
    <select id="route">
      {% for r in routes %}
        <option value="{{r['origin_label']}}|{{r['dest_label']}}" {% if r['origin_label']==default_o and r['dest_label']==default_d %}selected{% endif %}>
          {{r['origin_label']}} → {{r['dest_label']}}
        </option>
      {% endfor %}
    </select>

    <label>Days:</label>
    <select id="days">
      <option value="1">1</option>
      <option value="3">3</option>
      <option value="7" selected>7</option>
      <option value="14">14</option>
      <option value="30">30</option>
    </select>

    <button onclick="reload()">Refresh</button>
  </div>

  <canvas id="chart" height="120"></canvas>

  <script>
    const ctx = document.getElementById('chart').getContext('2d');
    let chart;

    async function load() {
      const route = document.getElementById('route').value;
      const days = document.getElementById('days').value;
      const [o, d] = route.split('|');
      const resp = await fetch(`/api/travel_times?origin=${encodeURIComponent(o)}&dest=${encodeURIComponent(d)}&days=${days}`);
      const data = await resp.json();
      const labels = data.points.map(p => p.ts);
      const mins = data.points.map(p => (p.seconds/60).toFixed(1));

      if (chart) chart.destroy();
      chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            # inside chart dataset label creation:
            label: `${data.origin} → ${data.dest} (${data.profile}, Google)`,
            data: mins,
            fill: false,
            tension: 0.2
          }]
        },
        options: {
          interaction: { mode: 'nearest', intersect: false },
          parsing: false,
          scales: {
            y: { title: { display: true, text: 'Minutes' } },
            x: { title: { display: true, text: 'Timestamp' } }
          },
          plugins: {
            legend: { display: true }
          }
        }
      });
    }

    function reload(){ load(); }
    load();
  </script>
</body>
</html>
"""

@app.get("/")
def index():
    routes = q("""
      SELECT origin_label, dest_label, COUNT(*) c
      FROM travel_times
      GROUP BY origin_label, dest_label
      ORDER BY c DESC
    """)
    default_o = routes[0]["origin_label"] if routes else ""
    default_d = routes[0]["dest_label"] if routes else ""
    return render_template_string(TEMPLATE, routes=routes, default_o=default_o, default_d=default_d)

@app.get("/api/travel_times")
def api_travel_times():
    origin = request.args.get("origin")
    dest = request.args.get("dest")
    days = int(request.args.get("days", "7"))
    rows = q("""
      SELECT strftime('%Y-%m-%d %H:%M', ts) ts, seconds, meters, profile
      FROM travel_times
      WHERE origin_label=? AND dest_label=?
        AND ts >= datetime('now', ?)
      ORDER BY ts ASC
    """, (origin, dest, f'-{days} days'))
    points = [dict(ts=r["ts"], seconds=r["seconds"], meters=r["meters"]) for r in rows]
    prof = rows[0]["profile"] if rows else "driving-car"
    return jsonify({"origin": origin, "dest": dest, "profile": prof, "points": points})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
