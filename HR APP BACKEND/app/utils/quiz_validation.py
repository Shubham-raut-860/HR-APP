"""Quiz question normalization and validation helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable
import re


DIFFICULTY_VALUES = ("easy", "medium", "hard")


class QuestionValidationError(ValueError):
    """Raised when a generated/parsed quiz question fails validation."""


def normalize_question_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def validate_question(question: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(question, dict):
        raise QuestionValidationError("Question must be an object")

    text_raw = question.get("question_text")
    if text_raw is None:
        text_raw = question.get("text")
    if not isinstance(text_raw, str) or not text_raw.strip():
        raise QuestionValidationError("Empty question text")
    question_text = text_raw.strip()

    options_raw = question.get("options", [])
    if not isinstance(options_raw, list):
        raise QuestionValidationError("Options must be a list")
    if len(options_raw) != 4:
        raise QuestionValidationError(f"Expected 4 options, got {len(options_raw)}")
    options: list[str] = []
    for option in options_raw:
        if not isinstance(option, str) or not option.strip():
            raise QuestionValidationError("Blank option")
        options.append(option.strip())

    correct_raw = question.get("correct_answer")
    try:
        correct_answer = int(correct_raw)
    except (TypeError, ValueError):
        raise QuestionValidationError("correct_answer must be an integer")
    if correct_answer < 0 or correct_answer >= len(options):
        raise QuestionValidationError(f"correct_answer {correct_answer} out of range")

    difficulty_raw = question.get("difficulty", "medium")
    difficulty = str(difficulty_raw or "").strip().lower()
    if difficulty not in DIFFICULTY_VALUES:
        raise QuestionValidationError("Invalid difficulty")

    skill_tag_raw = question.get("skill_tag")
    skill_tag: str | None
    if skill_tag_raw is None:
        skill_tag = None
    else:
        skill_tag = str(skill_tag_raw).strip() or None

    weight_raw = question.get("weight", 1)
    try:
        weight = int(weight_raw)
    except (TypeError, ValueError):
        weight = 1
    weight = max(1, min(10, weight))

    return {
        "question_text": question_text,
        "options": options,
        "correct_answer": correct_answer,
        "difficulty": difficulty,
        "skill_tag": skill_tag,
        "weight": weight,
    }


def deduplicate_questions(questions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    dropped = 0
    for question in questions:
        key = normalize_question_text(str(question.get("question_text", "")))
        if not key:
            dropped += 1
            continue
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        unique.append(question)
    return unique, dropped


def difficulty_counts(questions: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str((q or {}).get("difficulty", "")).strip().lower() for q in questions)


def rebalance_difficulty_distribution(
    questions: list[dict[str, Any]],
    *,
    expected_easy: int,
    expected_medium: int,
    expected_hard: int,
    fallback_factory: Callable[[int, int, int], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    expected = {
        "easy": max(0, int(expected_easy)),
        "medium": max(0, int(expected_medium)),
        "hard": max(0, int(expected_hard)),
    }

    selected: list[dict[str, Any]] = []
    counts = {"easy": 0, "medium": 0, "hard": 0}
    seen = {normalize_question_text(q["question_text"]) for q in questions}

    for question in questions:
        diff = question["difficulty"]
        if counts[diff] >= expected[diff]:
            continue
        selected.append(question)
        counts[diff] += 1

    missing_easy = expected["easy"] - counts["easy"]
    missing_medium = expected["medium"] - counts["medium"]
    missing_hard = expected["hard"] - counts["hard"]

    if (missing_easy > 0 or missing_medium > 0 or missing_hard > 0) and fallback_factory is not None:
        fallback_questions = fallback_factory(missing_easy, missing_medium, missing_hard)
        for fallback in fallback_questions:
            validated = validate_question(fallback)
            key = normalize_question_text(validated["question_text"])
            if key in seen:
                continue
            diff = validated["difficulty"]
            if counts[diff] >= expected[diff]:
                continue
            seen.add(key)
            selected.append(validated)
            counts[diff] += 1

    missing = {
        "easy": expected["easy"] - counts["easy"],
        "medium": expected["medium"] - counts["medium"],
        "hard": expected["hard"] - counts["hard"],
    }
    if any(v > 0 for v in missing.values()):
        raise QuestionValidationError(
            "Unable to satisfy difficulty distribution "
            f"(missing easy={missing['easy']}, medium={missing['medium']}, hard={missing['hard']})"
        )

    return selected
