import sqlite3

conn = sqlite3.connect('hr_platform.db')
cur = conn.cursor()

# Fix Job Descriptions
cur.execute("UPDATE job_descriptions SET location = 'Remote' WHERE location = 'RemoteRemote'")
cur.execute("UPDATE job_descriptions SET experience_max = 10 WHERE experience_max = 510") # Or 99? The user wanted 99 as default, but for this job 5-10 might have been intended.
cur.execute("UPDATE job_descriptions SET experience_max = 99 WHERE experience_max > 99")

# Fix User Role
cur.execute("UPDATE users SET role = 'candidate' WHERE email = 'shubham.raut860@gmail.com'")

conn.commit()
conn.close()
print("DB Cleaned: Fixed 'RemoteRemote', clamped experience_max, and set role to candidate.")
