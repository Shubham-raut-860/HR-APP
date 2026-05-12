import asyncio
from app.services.scoring_service import _degree_rank, compute_quiz_score, compute_final_score

# 1. Test _degree_rank
print('Degree rank test for Bachelors:', _degree_rank([{'degree': 'Bachelors in Computer Science'}]))
print('Degree rank test for Masters:', _degree_rank([{'degree': "Master's in CS"}]))

# 2. Test compute_quiz_score (zero point questions)
questions = [
    {'id': 'q1', 'correct_answer': 1, 'weight': 0, 'difficulty': 'medium', 'skill_tag': 'python'},
    {'id': 'q2', 'correct_answer': 2, 'weight': 5, 'difficulty': 'hard', 'skill_tag': 'java'},
]
answers = {'q1': 1, 'q2': 2}
raw_score, _, _ = compute_quiz_score(questions, answers)
print('Quiz score (should be 5):', raw_score)

# 3. Test compute_final_score (None quiz_score)
final = compute_final_score(resume_score=85.0, quiz_score=None, quiz_max_score=0, resume_weight=50, quiz_weight=50)
print('Final score when quiz is None (should be 85.0):', final)

print('SIMULATION SUCCESS')
