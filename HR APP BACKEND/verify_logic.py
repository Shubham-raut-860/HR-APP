import sys
import os

# Add Backend to path
sys.path.append(r'd:\shubham\HR APP\Backend')

from app.services import scoring_service
from app.models import JobDescription

print("--- Threshold Verification ---")
print(f"0.5 years -> {scoring_service.detect_candidate_tier(0.5)}")
print(f"2.0 years -> {scoring_service.detect_candidate_tier(2.0)}")
print(f"5.1 years -> {scoring_service.detect_candidate_tier(5.1)}")

print("\n--- Experience Max Default ---")
jd = JobDescription()
print(f"JobDescription().experience_max default: {jd.experience_max}")

print("\n--- Blended Weights Verification ---")
# Test interpolation around 1.0 and 5.0
print(f"0.5y weights: {scoring_service._blended_weights(0.5)}")
print(f"1.0y weights: {scoring_service._blended_weights(1.0)}")
print(f"3.0y weights: {scoring_service._blended_weights(3.0)}")
print(f"5.0y weights: {scoring_service._blended_weights(5.0)}")
print(f"6.0y weights: {scoring_service._blended_weights(6.0)}")
