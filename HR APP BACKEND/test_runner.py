import sys
import traceback
from app.services.scoring_service import _degree_rank, compute_quiz_score, compute_final_score

try:
    print("Degree rank test for Bachelors:", _degree_rank([{'degree': 'Bachelors in Computer Science'}]))
    print("Degree rank test for Masters:", _degree_rank([{'degree': "Master's in CS"}]))

    questions = [
        {'id': 'q1', 'correct_answer': 1, 'weight': 0, 'difficulty': 'medium', 'skill_tag': 'python'},
        {'id': 'q2', 'correct_answer': 2, 'weight': 5, 'difficulty': 'hard', 'skill_tag': 'java'},
    ]
    answers = {'q1': 1, 'q2': 2}
    raw_score, _, _ = compute_quiz_score(questions, answers)
    print("Quiz score:", raw_score)

    final = compute_final_score(resume_score=85.0, quiz_score=None, quiz_max_score=0, resume_weight=50, quiz_weight=50)
    print("Final score when quiz is None:", final)
    print("SIMULATION SUCCESS")
except Exception as e:
    with open('pytest_error.txt', 'w', encoding='utf-8') as f:
        traceback.print_exc(file=f)
