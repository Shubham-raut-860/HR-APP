import sqlite3

conn = sqlite3.connect('hr_platform.db')
cur = conn.cursor()
cur.execute('SELECT id, title, location, experience_min, experience_max FROM job_descriptions WHERE title LIKE "%Python%"')
rows = cur.fetchall()
for row in rows:
    print(row)
conn.close()
