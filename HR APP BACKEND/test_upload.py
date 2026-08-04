import requests
import sqlite3

# 1. Login to get token
url = "http://localhost:8000/auth/login"
# LoginRequest expects 'email' and 'password' as JSON
data = {
    "email": "[email-redacted]",
    "password": "Password123"
}
try:
    response = requests.post(url, json=data)
    print("Login Status:", response.status_code)
    if response.status_code == 200:
        token = response.json().get("access_token")
        print("Token acquired")
    else:
        print("Login failed:", response.text)
        token = None
except Exception as e:
    print("Error during login:", e)
    token = None

if not token:
    exit(1)

# 2. Check Jobs
headers = {"Authorization": f"Bearer {token}"}
list_jobs_url = "http://localhost:8000/jd/"
jobs_resp = requests.get(list_jobs_url, headers=headers)
if jobs_resp.status_code != 200:
    print("Failed to list jobs:", jobs_resp.text)
    jobs = []
else:
    jobs = jobs_resp.json()

python_job = next((j for j in jobs if "Python" in (j.get("title") or "")), None)

if not python_job:
    print("Creating Python Developer job...")
    create_job_url = "http://localhost:8000/jd/"
    jd_data = {
        "title": "Python Developer",
        "role": "Software Engineer",  # REQUIRED by JDCreate
        "location": "Remote",
        "experience_min": 2,
        "experience_max": 99,
        "must_have_skills": ["Python", "FastAPI", "SQLAlchemy"],
        "good_to_have_skills": ["Docker", "Redis"],
        "description": "Senior Python Developer role for building high-scale APIs."
    }
    create_resp = requests.post(create_job_url, headers=headers, json=jd_data)
    if create_resp.status_code in [200, 201]:
        python_job = create_resp.json()
        print("Job created:", python_job["id"])
    else:
        print("Failed to create job:", create_resp.text)
        exit(1)

job_id = python_job["id"]
print(f"Using Job ID: {job_id}")

# 3. Upload Resume
upload_url = "http://localhost:8000/resumes/upload"
files = {"file": open(r"C:\Users\Shubh\Downloads\Resume.pdf", "rb")}
form_data = {"job_id": job_id}
try:
    up_resp = requests.post(upload_url, headers=headers, data=form_data, files=files)
    print("Upload Status:", up_resp.status_code)
    print("Upload Response:", up_resp.text)
except Exception as e:
    print("Error during upload:", e)
