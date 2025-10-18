import sqlite3
import pandas as pd

conn = sqlite3.connect("sanitas_doctors.db")

# How many rows
count = conn.execute("SELECT COUNT(*) FROM doctors;").fetchone()[0]
print(f"Total doctors in database: {count}")

# Fetch a few joined rows (no DISTINCT+separator conflict)
df = pd.read_sql_query("""
SELECT d.id, d.name, d.profile_url, d.phones_normalized,
       ds.specialty, dc.center
FROM doctors d
LEFT JOIN doctor_specialties ds ON ds.doctor_id = d.id
LEFT JOIN doctor_centers dc ON dc.doctor_id = d.id
LIMIT 20;
""", conn)

print(df.head(10))

conn.close()
