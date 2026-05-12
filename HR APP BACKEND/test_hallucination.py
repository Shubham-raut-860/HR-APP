import asyncio
import json
import os
from pprint import pprint
from dotenv import load_dotenv

load_dotenv()

from app.services.gemini_service import parse_resume, score_resume_against_jd
from app.services.file_service import extract_text_from_pdf

async def main():
    pdf_path = os.path.join("tests", "eval", "real_data", "Shahid Ali-BE.Net Developer.pdf")
    
    # 1. Extract
    print(f"Reading {pdf_path}...")
    with open(pdf_path, 'rb') as f:
        raw_text = extract_text_from_pdf(f.read())
    
    # 2. Parse
    print("Parsing resume with AI...")
    parsed = await parse_resume(raw_text)
    
    # 3. Score against dummy JD
    print("Scoring resume (Checking for hallucination)...")
    must_haves = [".NET", "C#", "SQL Server", "Git", "Caching"]
    good_to_haves = ["Azure", "Docker", "Microservices"]
    
    score = await score_resume_against_jd(
        parsed_resume=parsed,
        job_title=".NET Developer",
        exp_min=2,
        exp_max=5,
        must_have=must_haves,
        good_to_have=good_to_haves,
        description="Looking for a solid .NET backend dev."
    )
    
    print("\n--- RESULTS ---")
    print(f"Candidate matched Must-Haves: {score['matched_must_have']}")
    print(f"Candidate missing Must-Haves: {score['missing_must_have']}")
    print(f"Reasoning: {score['reasoning']}")
    
    if "Git" in score['matched_must_have'] or "Caching" in score['matched_must_have']:
        print("\n\u274c FAILED: Hallucinated skills that are not in the PDF.")
    else:
        print("\n\u2705 PASSED: Correctly identified missing skills!")

if __name__ == "__main__":
    asyncio.run(main())
