import sqlite3
conn = sqlite3.connect('hr_platform.db')
cur = conn.cursor()
print("--- JOBS ---")
cur.execute('SELECT id, title, created_at FROM job_descriptions ORDER BY created_at DESC LIMIT 5')
for row in cur.fetchall():
    print(row)

print("--- USERS ---")
cur.execute('SELECT id, email, role FROM users WHERE email="[email-redacted]"')
for row in cur.fetchall():
    print(row)
conn.close()
