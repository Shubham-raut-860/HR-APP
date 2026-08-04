import asyncio
import httpx
from jose import jwt
import json

JWT_SECRET='your_jwt_secret_here'
API_URL = "http://127.0.0.1:8000"

async def run_job(client, headers, agent_type, payload_task):
    payload = {
        "agent_type": agent_type,
        "task": payload_task,
        "metadata": {"test_name": f"Bulk Test {agent_type}"}
    }
    print(f"\n[+] Submitting Run to API for {agent_type}...")
    resp = await client.post(f"{API_URL}/runs", json=payload, headers=headers)
    if resp.status_code != 201:
        print(f"[-] Failed to create run: HTTP {resp.status_code}")
        return None
    data = resp.json()
    run_id = data["run_id"]
    print(f"    Run ID : {run_id}")
    return run_id

async def run_test():
    token = jwt.encode({"sub": "tenant_123", "tenant_id": "tenant_123"}, JWT_SECRET, algorithm="HS256")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Submit multiple runs
        r1 = await run_job(client, headers, "jd_parser", '{"doc_text": "Need a Data Scientist experienced in Python, SQL, and Machine Learning."}')
        r2 = await run_job(client, headers, "career_analyst", '{"resume_text": "Data Analyst with 5 years experience in SQL and Tableau.", "target_role": "Data Scientist"}')
        r3 = await run_job(client, headers, "career_analyst", '{"resume_text": "Software Engineer, C++ and Java.", "target_role": "Python Backend Engineer"}')
        
        runs = [r1, r2, r3]
        
        # Wait for them
        for r_id in runs:
            if not r_id: continue
            for i in range(30):
                await asyncio.sleep(2)
                resp = await client.get(f"{API_URL}/runs/{r_id}", headers=headers)
                st = resp.json().get("status")
                print(f"    {r_id} -> {st}")
                if st in ("completed", "failed"):
                    break

if __name__ == "__main__":
    asyncio.run(run_test())
