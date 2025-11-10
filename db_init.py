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

cur.execute("""
CREATE TABLE IF NOT EXISTS travel_times (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
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

cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_ts ON travel_times(ts);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_tt_route ON travel_times(origin_label, dest_label);")

con.commit()
con.close()
print("DB ready: commute.db")
