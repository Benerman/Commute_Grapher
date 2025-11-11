from flask import Flask, render_template, request, send_file, abort, jsonify
import os, sqlite3, io
from datetime import datetime, timedelta, time
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "commute.db")
HOME_LABEL = os.getenv("HOME_LABEL", "Home")
WORK_LABEL = os.getenv("WORK_LABEL", "Work")


def ensure_schema():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS locations (
      id INTEGER PRIMARY KEY,
      label TEXT NOT NULL UNIQUE,
      address TEXT NOT NULL,
      lat REAL,
      lon REAL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS travel_times (
      id INTEGER PRIMARY KEY,
      ts DATETIME DEFAULT CURRENT_TIMESTAMP,
      batch_id TEXT NOT NULL,
      batch_ts DATETIME NOT NULL,
      origin_label TEXT NOT NULL,
      dest_label TEXT NOT NULL,
      description TEXT NOT NULL,
      meters INTEGER NOT NULL,
      miles FLOAT NOT NULL,
      duration_seconds INTEGER NOT NULL,
      duration_static INTEGER NOT NULL,
      duration_minutes INTEGER NOT NULL
    );
    """)
    con.commit()
    con.close()

ensure_schema()

app = Flask(__name__)

def get_rows(direction: str, days: int):
    if direction == "H2W":
        origin, dest = HOME_LABEL, WORK_LABEL
    else:
        origin, dest = WORK_LABEL, HOME_LABEL

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    sql = """
      SELECT ts, origin_label, dest_label, description, miles, duration_minutes, duration_static
      FROM travel_times
      WHERE origin_label = ? AND dest_label = ?
        AND ts >= datetime('now', ?)
      ORDER BY ts ASC
    """
    params = (origin, dest, f"-{int(days)} days")
    rows = [dict(r) for r in cur.execute(sql, params)]
    con.close()
    return rows

@app.route("/")
def index():
    direction = request.args.get("direction", "H2W").upper()
    days = int(request.args.get("days", 14))
    chart = request.args.get("chart", "line")
    show_traffic = request.args.get("traffic", "1") == "1"
    show_static = request.args.get("static", "1") == "1"
    limit = request.args.get("limit", "").strip()

    rows = get_rows(direction, days)
    if limit.isdigit():
        rows = rows[-int(limit):]

    return render_template(
        "index.html",
        direction=direction,
        days=days,
        chart=chart,
        show_traffic=show_traffic,
        show_static=show_static,
        rows=rows
    )

@app.route("/chart.png")
def chart_png():

    direction = request.args.get("direction", "H2W").upper()
    days = int(request.args.get("days", 14))
    chart = request.args.get("chart", "line")
    show_traffic = request.args.get("traffic", "1") == "1"
    show_static = request.args.get("static", "1") == "1"
    limit = request.args.get("limit", "").strip()
    filter_hours = request.args.get("filter_hours", "1") == "1"  # keep 5:00–19:00 filter on by default

    rows = get_rows(direction, days)

    # Filter to 05:00–19:00 if enabled
    if filter_hours:
        START, END = time(5, 0), time(19, 0)
        rows = [r for r in rows if START <= datetime.fromisoformat(r["ts"]).time() <= END]

    if limit.isdigit():
        rows = rows[-int(limit):]

    fig, ax = plt.subplots(figsize=(9, 4.5))

    if not rows:
        # Show a placeholder image instead of 404
        ax.axis("off")
        title = "Home → Work" if direction == "H2W" else "Work → Home"
        ax.text(0.5, 0.6, "No data to plot", ha="center", va="center", fontsize=18)
        ax.text(0.5, 0.5, f"{title}", ha="center", va="center", fontsize=12)
        ax.text(0.5, 0.4, f"Window: 05:00–19:00 • Last {days} days", ha="center", va="center", fontsize=10)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    xs = [datetime.fromisoformat(r["ts"]) for r in rows]
    y_traf = [r["duration_minutes"] for r in rows]
    y_stat = [r["duration_static"] for r in rows]

    if chart == "bar":
        width = 0.4
        if show_traffic:
            ax.bar(range(len(xs)), y_traf, width, label="With traffic (min)")
        if show_static:
            base_x = [x + (width if show_traffic else 0) for x in range(len(xs))]
            ax.bar(base_x, y_stat, width, label="No traffic (min)")
        ax.set_xticks(range(len(xs)))
        ax.set_xticklabels([dt.strftime("%m-%d %H:%M") for dt in xs], rotation=45, ha="right")
    elif chart == "area":
        if show_traffic:
            ax.fill_between(xs, y_traf, alpha=0.3, label="With traffic (min)")
            ax.plot(xs, y_traf)
        if show_static:
            ax.fill_between(xs, y_stat, alpha=0.3, label="No traffic (min)")
            ax.plot(xs, y_stat)
        ax.tick_params(axis="x", labelrotation=45)
    elif chart == "scatter":
        if show_traffic:
            ax.scatter(xs, y_traf, label="With traffic (min)")
        if show_static:
            ax.scatter(xs, y_stat, label="No traffic (min)")
        ax.tick_params(axis="x", labelrotation=45)
    else:  # line
        if show_traffic:
            ax.plot(xs, y_traf, label="With traffic (min)")
        if show_static:
            ax.plot(xs, y_stat, label="No traffic (min)")
        ax.tick_params(axis="x", labelrotation=45)

    ax.set_ylabel("Minutes")
    title = "Home → Work" if direction == "H2W" else "Work → Home"
    ax.set_title(f"Commute durations • {title} • 05:00–19:00 • last {days} days")
    ax.legend(loc="best")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/data.json")
def data_json():
    direction = request.args.get("direction", "H2W").upper()
    days = int(request.args.get("days", 14))
    limit = request.args.get("limit", "").strip()
    filter_hours = request.args.get("filter_hours", "1") == "1"

    rows = get_rows(direction, days)

    if filter_hours:
        START, END = time(5, 0), time(19, 0)
        out = []
        for r in rows:
            try:
                dt = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            if START <= dt.time() <= END:
                out.append(r)
        rows = out

    if limit.isdigit():
        rows = rows[-int(limit):]

    return jsonify(rows)


@app.route("/debug/summary")
def debug_summary():
    def _bounds(rs):
        if not rs: return {"count": 0}
        try:
            ts_vals = [datetime.fromisoformat(r["ts"]) for r in rs]
            return {
                "count": len(rs),
                "min_ts": min(ts_vals).isoformat(sep=" ", timespec="seconds"),
                "max_ts": max(ts_vals).isoformat(sep=" ", timespec="seconds"),
            }
        except Exception:
            return {"count": len(rs)}

    def _filter_5to19(rs):
        START, END = time(5, 0), time(19, 0)
        out = []
        for r in rs:
            try:
                dt = datetime.fromisoformat(r["ts"])
            except Exception:
                continue
            if START <= dt.time() <= END:
                out.append(r)
        return out

    out = {}
    for d in ("H2W", "W2H"):
        r14 = get_rows(d, 14)
        r30 = get_rows(d, 30)
        out[d] = {
            "14d_all": _bounds(r14),
            "14d_5to19": _bounds(_filter_5to19(r14)),
            "30d_all": _bounds(r30),
            "30d_5to19": _bounds(_filter_5to19(r30)),
        }
    return jsonify(out)



if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
