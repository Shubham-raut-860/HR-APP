import json

try:
    with open("tests/eval/real_data/last_run_results.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    print("----- NEW RESULTS -----")
    for row in data:
        print(f"\n[{row['filename']}]")
        print(f"DeepEval Score: {row['evaluation']['deepeval_metrics'][0]['score']}")
        print(f"DeepEval Reason: {row['evaluation']['deepeval_metrics'][0]['reason']}")
except Exception as e:
        print(f"Error reading file: {e}")
