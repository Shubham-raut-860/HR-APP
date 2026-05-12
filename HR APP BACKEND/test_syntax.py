import ast, os
files = [
  'app/routers/resumes.py',
  'app/routers/quiz.py',
  'app/routers/candidate_portal.py',
  'app/routers/jd.py',
  'app/routers/analytics.py',
  'app/routers/settings_router.py',
  'app/models.py',
  'app/services/scoring_service.py',
]
for f in files:
    try:
        if os.path.exists(f):
            ast.parse(open(f, encoding='utf-8').read())
            print(f'✅ {f}')
        else:
            print(f'❌ {f}: File not found')
    except SyntaxError as e:
        print(f'❌ {f}: {e}')
