import json

try:
    with open('tests/eval/real_data/last_run_results.json', 'rb') as f:
        raw = f.read()
    
    # PowerShell sometimes writes UTF-16 LE with BOM
    if raw.startswith(b'\xff\xfe'):
        text = raw.decode('utf-16-le')
    elif raw.startswith(b'\xfe\xff'):
        text = raw.decode('utf-16-be')
    else:
        text = raw.decode('utf-8', errors='ignore')
        
    data = json.loads(text)
    
    print("--- DEEPEVAL METRICS (GEval) ---")
    for r in data:
        metrics = r.get("evaluation", {}).get("deepeval_metrics", [])
        if metrics:
            print(f"\n[{r.get('resume', 'Unknown')}]")
            print(f"Passed: {metrics[0]['passed']}")
            print(f"Score:  {metrics[0]['score']}")
            print(f"Reason: {metrics[0]['reason']}")
except Exception as e:
    print("Error:", e)
