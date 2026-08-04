import httpx
import os
import time
import base64

BASE_URL = "http://127.0.0.1:8000"

# Minimal valid PDF 1.4 structure
MINIMAL_PDF = base64.b64decode(
    "JVBERi0xLjQKJfbifzEKMSAwIG9iaiA8PC9UeXBlL0NhdGFsb2cvUGFnZXMgMiAwIFI+P"
    "mVuZG9iaiAyIDAgb2JqIDw8L1R5cGUvUGFnZXMvS2lkc1szIDAgUl0vQ291bnQgMT4+Z"
    "W5kb2JqIDMgMCBvYmogPDwvVHlwZS9QYWdlL1BhcmVudCAyIDAgUi9NZWRpYUJveFswID"
    "AgNjEyIDc5Ml0vQ29udGVudHMgNCAwIFI+PmVuZG9iaiA0IDAgb2JqIDw8L0xlbmd0aCA"
    "0ND4+c3RyZWFtCkJULyYxIDEyIFRmIDcwIDcwMCBUZCAoUmVzdW1lIGZvciBBdWRpdClU"
    "aiBFVAplbmRzdHJlYW0KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKM"
    "DAwMDAwMDAxOCAwMDAwMCBuIAowMDAwMDAwMDY1IDAwMDAwIG4gCjAwMDAwMDAxMTcgMD"
    "AwMDAgbiAKMDAwMDAwMDIxMiAwMDAwMCBuIAp0cmFpbGVyIDw8L1NpemUgNS9Sb290ID"
    "EgMCBSPj4Kc3RhcnR4cmVmCjMwNwpfX0VPRgo="
)

def run_candidate_flow():
    # Set high timeout for AI processing
    timeout = httpx.Timeout(60.0, connect=60.0)
    with httpx.Client(timeout=timeout) as client:
        timestamp = int(time.time())
        # 1a. HR creates a JD
        hr_email = f"hr_{timestamp}@company.com"
        print(f"1a. Registering HR: {hr_email}")
        res = client.post(f"{BASE_URL}/auth/register", json={
            "email": hr_email, "password": "Password123!", "full_name": "Test HR", "role": "hr"
        })
        assert res.status_code in [200, 201], f"HR Register Failed: {res.text}"
        
        res = client.post(f"{BASE_URL}/auth/login", json={"email": hr_email, "password": "Password123!"})
        hr_token = res.json()["access_token"]
        
        print("1b. Creating Job Description as HR...")
        jd_res = client.post(f"{BASE_URL}/jd/", json={
            "title": f"Software Engineer Audit {timestamp}",
            "role": "Software Engineer",
            "experience_min": 1,
            "experience_max": 5,
            "must_have_skills": ["Python", "FastAPI"],
            "good_to_have_skills": ["Docker"],
            "description": "A test software engineering role for the audit.",
            "resume_weight": 50,
            "quiz_weight": 50,
            "pass_threshold": 60,
            "is_active": True
        }, headers={"Authorization": f"Bearer {hr_token}"})
        assert jd_res.status_code in [200, 201], f"JD Create Failed: {jd_res.text}"
        job_id = jd_res.json()["id"]
        print(f"JD Created with ID: {job_id}")

        # 2a. Candidate registers
        cand_email = f"cand_{timestamp}@candidate.com"
        print(f"2a. Registering Candidate: {cand_email}")
        res = client.post(f"{BASE_URL}/auth/register", json={
            "email": cand_email, "password": "Password123!", "full_name": "Audit Candidate", "role": "candidate"
        })
        assert res.status_code in [200, 201], f"Candidate Register Failed: {res.text}"
        
        res = client.post(f"{BASE_URL}/auth/login", json={"email": cand_email, "password": "Password123!"})
        cand_token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {cand_token}"}
        
        print("2b. Fetching available Jobs...")
        res = client.get(f"{BASE_URL}/candidate/jobs", headers=headers)
        jobs = res.json()
        assert len(jobs) > 0, f"No jobs available to apply to! {jobs}"
        
        print(f"3. Applying to Job: {job_id}...")
        with open("valid_mock_resume.pdf", "wb") as f:
            f.write(MINIMAL_PDF)
            
        with open("valid_mock_resume.pdf", "rb") as f:
            files = {"file": ("valid_mock_resume.pdf", f, "application/pdf")}
            res = client.post(f"{BASE_URL}/candidate/apply/{job_id}", files=files, headers=headers)
            print("Apply Status:", res.status_code)
            if res.status_code not in [200, 201]:
                print("Error Details:", res.text)
            
        print("\nSUCCESS: Candidate setup complete.")
        print(f"Candidate Email: {cand_email}")
        print(f"Password: Password123!")

if __name__ == "__main__":
    try:
        run_candidate_flow()
    except Exception as e:
        print("FAIL", e)
