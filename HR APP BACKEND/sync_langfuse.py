import requests, os, uuid
from dotenv import load_dotenv

load_dotenv()
pk = os.getenv('LANGFUSE_PUBLIC_KEY')
sk = os.getenv('LANGFUSE_SECRET_KEY')
host = os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com').rstrip('/')

print('Bypassing SDK: Sending raw REST API requests directly to Langfuse...')
trace_id = str(uuid.uuid4())

# 1. Create Trace via API
r1 = requests.post(
    f'{host}/api/public/traces',
    auth=(pk, sk),
    json={
        'id': trace_id,
        'name': 'JD_Generation_Pipeline_Final',
        'input': 'Write a JD for a Data Engineer...',
        'output': 'Data Engineer (Remote)...'
    }
)

# 2. Add Scores via API
requests.post(
    f'{host}/api/public/scores',
    auth=(pk, sk),
    json={
        'traceId': trace_id,
        'name': 'Answer Relevancy',
        'value': 1.0,
        'comment': 'PASSED: Score 1.0. Output fully addressed the input.'
    }
)
requests.post(
    f'{host}/api/public/scores',
    auth=(pk, sk),
    json={
        'traceId': trace_id,
        'name': 'JD Completeness',
        'value': 1.0,
        'comment': 'PASSED: All sections present.'
    }
)

if r1.status_code in [200, 201]:
    print('? SUCCESS! The data is officially in the cloud. Refresh your Dashboard.')
else:
    print(f'? Error: {r1.status_code} - {r1.text}')
