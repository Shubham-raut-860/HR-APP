import ast
import sys

def get_funcs(file_path, func_names=None):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        tree = ast.parse(code)
        filename = file_path.split('/')[-1]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not func_names or node.name in func_names:
                    print(f'{filename}: {node.name}() lines {node.lineno}-{node.end_lineno}')
    except Exception as e:
        print(f'Error reading {file_path}: {e}')

get_funcs('d:/shubham/HR APP/Backend/app/routers/jd.py')
get_funcs('d:/shubham/HR APP/Backend/app/routers/quiz.py', ['_assert_quiz_owner', 'send_quiz_links', 'evaluate_code_endpoint', 'generate_quiz', 'submit_quiz'])
get_funcs('d:/shubham/HR APP/Backend/app/routers/resumes.py', ['upload_bulk_resumes', 'upload_bulk_pool', 'import_from_pool', 'list_candidates', '_process_resume', 'download_resume'])
get_funcs('d:/shubham/HR APP/Backend/app/routers/analytics.py', ['export_pdf', 'get_summary', 'get_rankings'])
get_funcs('d:/shubham/HR APP/Backend/app/routers/admin.py')
get_funcs('d:/shubham/HR APP/Backend/app/routers/notifications.py')
get_funcs('d:/shubham/HR APP/Backend/app/routers/candidate_portal.py', ['apply_to_job', 'list_public_jobs'])
get_funcs('d:/shubham/HR APP/Backend/app/services/scoring_service.py', ['compute_resume_score_with_ai_override', 'skill_match_score'])
get_funcs('d:/shubham/HR APP/Backend/app/services/gemini_service.py')
get_funcs('d:/shubham/HR APP/Backend/app/services/encryption_service.py')
get_funcs('d:/shubham/HR APP/Backend/app/services/notification_service.py')
