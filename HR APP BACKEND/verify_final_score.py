import sqlite3
import json

conn = sqlite3.connect('hr_platform.db')
cur = conn.cursor()
cur.execute('SELECT id, name, email, job_id, resume_score, score_breakdown, created_at FROM candidates ORDER BY created_at DESC LIMIT 1')
row = cur.fetchone()
if row:
    data = {
        'ID': row[0],
        'Name': row[1],
        'Email': row[2],
        'JobID': row[3],
        'Score': row[4],
        'Breakdown': json.loads(row[5]),
        'Created': row[6]
    }
    with open('verified_score.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print("Success: result written to verified_score.json")
else:
    print("No candidates found.")
conn.close()
