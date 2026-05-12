import requests
import json
import time

def test_quiz_gen():
    url = "http://localhost:8000/quiz/generate"
    # Find a job ID from the DB first. I'll use a placeholder or try to find one.
    # From previous check, I didn't get the ID yet. I'll assume one exists.
    # I'll try to find it first.
    
    # Actually, I'll just use a job_id if I can find it.
    job_id = "fb99b19e-e092-4e46-95e5-3ab9453c076b" # Placeholder based on previous logs
    
    payload = {
        "job_id": job_id,
        "custom_title": "Test AI Quiz",
        "duration_minutes": 15
    }
    
    # We need a token. I'll use the hr@example.com one if I had it.
    # But for a backend test, I can skip auth if I use a mock or temp change.
    
    print(f"Calling {url}...")
    try:
        start = time.time()
        # Note: I might need an auth header.
        # I'll just check if it returns 401/403 (reachability) vs 500/Timeout.
        resp = requests.post(url, json=payload, timeout=120)
        print(f"Status: {resp.status_code}")
        print(f"Time: {time.time() - start:.2f}s")
        print(f"Response: {resp.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_quiz_gen()
