import sqlite3
import bcrypt

conn = sqlite3.connect('hr_platform.db')
cur = conn.cursor()
pwd = 'Password123'
hashed = bcrypt.hashpw(pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
cur.execute("UPDATE users SET hashed_password = ? WHERE email = 'shubham.raut860@gmail.com'", (hashed,))
conn.commit()
conn.close()
print("Candidate shubham.raut860@gmail.com password updated to Password123")
