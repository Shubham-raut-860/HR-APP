from __future__ import annotations

import asyncio
from typing import Any

from app.services import harness_agent_client


def _ok(agent_type: str, detail: str = "pass") -> dict[str, str]:
    return {"agent_type": agent_type, "status": "pass", "detail": detail}


def _fail(agent_type: str, detail: str) -> dict[str, str]:
    return {"agent_type": agent_type, "status": "fail", "detail": detail}


async def _eval_resume_parser(auth_header: str | None) -> dict[str, str]:
    agent_type = "resume_parser"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "doc_text": (
                    "Romil Desai\n"
                    "Email: romildesai20000@gmail.com\n"
                    "Skills: .NET Core, C#, Web API, SQL Server\n"
                    "Experience: 3 years\n"
                    "Education: B.E. Computer Engineering"
                ),
            },
            auth_header,
        )
        parsed = result.get("parsed_resume") if isinstance(result, dict) else None
        if not isinstance(parsed, dict):
            return _fail(agent_type, f"missing parsed_resume: {type(result).__name__}")
        required = ("name", "skills", "experience_years", "education")
        missing = [k for k in required if k not in parsed]
        if missing:
            return _fail(agent_type, f"missing keys: {missing}")
        if not isinstance(parsed.get("skills"), list):
            return _fail(agent_type, "skills is not a list")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_resume_scorer(auth_header: str | None) -> dict[str, str]:
    agent_type = "resume_scorer"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "parsed_resume": {
                    "name": "Akshay Chirde",
                    "skills": [".NET Core", "C#", "Web API", "SQL Server"],
                    "normalized_skills": [".net core", "c#", "web api", "sql server"],
                    "experience_years": 4,
                    "education": ["B.E. Computer Engineering"],
                    "projects": ["API platform modernization"],
                },
                "job_title": "Net Core Developer",
                "experience_min": 3,
                "experience_max": 6,
                "must_have_skills": [".NET Core", "C#", "Web API", "SQL Server"],
                "good_to_have_skills": ["Design Patterns"],
                "job_description": "Build, test, and maintain .NET Core APIs.",
            },
            auth_header,
        )
        score = result.get("score_result") if isinstance(result, dict) else None
        if isinstance(score, dict):
            result = score
        if not isinstance(result, dict):
            return _fail(agent_type, "missing score payload")
        value = float(result.get("resume_score", -1))
        if value < 0 or value > 100:
            return _fail(agent_type, f"resume_score out of range: {value}")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_jd_generator(auth_header: str | None) -> dict[str, str]:
    agent_type = "jd_generator"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "role": "Python Backend Engineer",
                "experience_min": 2,
                "experience_max": 5,
                "location": "Remote",
                "additional_context": "Fintech APIs and microservices",
            },
            auth_header,
        )
        jd_data = result.get("jd_data") if isinstance(result, dict) else None
        if not isinstance(jd_data, dict):
            return _fail(agent_type, "missing jd_data")
        if not jd_data.get("must_have_skills"):
            return _fail(agent_type, "must_have_skills empty")
        if not str(jd_data.get("description") or "").strip():
            return _fail(agent_type, "description empty")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_jd_parser(auth_header: str | None) -> dict[str, str]:
    agent_type = "jd_parser"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "doc_text": (
                    "Role: Net Core Developer\n"
                    "Experience: 3-6 years\n"
                    "Must have: .NET Core, C#, Web API, SQL Server\n"
                    "Location: Remote"
                ),
            },
            auth_header,
        )
        parsed = result.get("parsed_job") if isinstance(result, dict) else None
        if not isinstance(parsed, dict):
            return _fail(agent_type, "missing parsed_job")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_quiz_generator(auth_header: str | None) -> dict[str, str]:
    agent_type = "quiz_generator"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "jd_text": "Net Core Developer with Web API and SQL Server.",
                "skills": [".NET Core", "C#", "Web API", "SQL Server"],
                "easy": 2,
                "medium": 2,
                "hard": 1,
            },
            auth_header,
        )
        questions = result.get("questions") if isinstance(result, dict) else None
        if not isinstance(questions, list) or len(questions) != 5:
            return _fail(agent_type, f"unexpected questions len: {0 if not isinstance(questions, list) else len(questions)}")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_embedding(auth_header: str | None) -> dict[str, str]:
    agent_type = "embedding"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {"text": "Test embedding for .NET Core developer profile"},
            auth_header,
        )
        embedding = result.get("embedding") if isinstance(result, dict) else None
        if not isinstance(embedding, list):
            return _fail(agent_type, "embedding missing")
        return _ok(agent_type, detail=f"len={len(embedding)}")
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def _eval_career_analyst(auth_header: str | None) -> dict[str, str]:
    agent_type = "career_analyst"
    try:
        result = await harness_agent_client.run_agent(
            agent_type,
            {
                "candidate_name": "Shubham Raut",
                "experience_years": 3.5,
                "skills": [".NET Core", "C#", "SQL Server", "Azure"],
                "work_history": [{"role": "Software Developer", "years": 3.5}],
                "education": ["B.E. Computer Engineering"],
                "career_breaks": [],
                "target_role": "Senior .NET Developer",
            },
            auth_header,
        )
        analysis = result.get("career_analysis") if isinstance(result, dict) else None
        if not isinstance(analysis, dict):
            return _fail(agent_type, "missing career_analysis")
        return _ok(agent_type)
    except Exception as exc:
        return _fail(agent_type, str(exc))


async def eval_all_agents(auth_header: str | None) -> list[dict[str, str]]:
    tasks = [
        _eval_resume_parser(auth_header),
        _eval_resume_scorer(auth_header),
        _eval_jd_generator(auth_header),
        _eval_jd_parser(auth_header),
        _eval_quiz_generator(auth_header),
        _eval_embedding(auth_header),
        _eval_career_analyst(auth_header),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: list[dict[str, str]] = []
    for idx, row in enumerate(results):
        if isinstance(row, Exception):
            out.append(
                {
                    "agent_type": f"unknown_{idx}",
                    "status": "fail",
                    "detail": str(row),
                }
            )
        else:
            out.append(row)
    return out
