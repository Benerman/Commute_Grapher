import sqlite3

con = sqlite3.connect("commute.db")
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL UNIQUE,
  address TEXT NOT NULL,
  lat REAL,
  lon REAL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# Fresh schema includes batch_id + batch_ts so a run's inserts are grouped
cur.execute("""
CREATE TABLE IF NOT EXISTS travel_times (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,         -- per-row insert time
  batch_id TEXT NOT NULL,                         -- same for all rows in one run
  batch_ts DATETIME NOT NULL,                     -- run timestamp (consistent across rows)
  origin_label TEXT NOT NULL,
  dest_label TEXT NOT NULL,
  description TEXT NOT NULL,
  meters INTEGER NOT NULL,
  miles FLOAT NOT NULL,
  duration_seconds INTEGER NOT NULL,              -- raw seconds from routes.duration
  duration_static INTEGER NOT NULL,               -- "no traffic" minutes
  duration_minutes INTEGER NOT NULL               -- "with traffic" minutes
);
""")

# Helpful indices for querying batches & routes
cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_batch ON travel_times(batch_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_batch_ts ON travel_times(batch_ts);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_route ON travel_times(origin_label, dest_label);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_ts ON travel_times(ts);")

con.commit()
con.close()
print("DB ready: commute.db")
