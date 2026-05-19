from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import AgentError
from app.agents.specialized import (
    CareerAnalystAgent,
    CodeEvaluationAgent,
    CoverLetterAgent,
    DeduplicationAgent,
    NotificationAgent,
    RankingAgent,
    EmbeddingAgent,
    FileExtractionAgent,
    JDGeneratorAgent,
    JDParserAgent,
    QuizAgent,
    ResumeBuilderAgent,
    ResumeEnhancerAgent,
    ResumeParserAgent,
    ScoringAgent,
)

class HRMultiAgentRuntimeError(RuntimeError):
    def __init__(self, agent_name: str, message: str):
        self.agent_name = agent_name
        super().__init__(f"{agent_name}: {message}")


class HRMultiAgentRuntime:
    """
    Native HR multi-agent runtime.

    This orchestrates task-specific specialized agents directly in-process
    (independent of Harness availability) and provides a single runtime
    contract for routers/services.
    """

    def __init__(self) -> None:
        self._agents = {
            "file_extraction_agent": FileExtractionAgent(),
            "resume_parser_agent": ResumeParserAgent(),
            "jd_parser_agent": JDParserAgent(),
            "jd_generator_agent": JDGeneratorAgent(),
            "embedding_agent": EmbeddingAgent(),
            "scoring_agent": ScoringAgent(),
            "deduplication_agent": DeduplicationAgent(),
            "quiz_agent": QuizAgent(),
            "code_evaluation_agent": CodeEvaluationAgent(),
            "resume_enhancer_agent": ResumeEnhancerAgent(),
            "resume_builder_agent": ResumeBuilderAgent(),
            "cover_letter_agent": CoverLetterAgent(),
            "career_analyst_agent": CareerAnalystAgent(),
            "notification_agent": NotificationAgent(),
            "ranking_agent": RankingAgent(),
        }

    @staticmethod
    def _merge_updates(state: dict[str, Any], updates: dict[str, Any]) -> None:
        trace = updates.get("_agent_trace")
        if isinstance(trace, list):
            state.setdefault("_agent_trace", []).extend(trace)
        state.update({k: v for k, v in updates.items() if k != "_agent_trace"})

    async def run_agent(self, agent_name: str, state: dict[str, Any]) -> dict[str, Any]:
        agent = self._agents.get(agent_name)
        if agent is None:
            raise HRMultiAgentRuntimeError(agent_name, "agent not registered")
        try:
            updates = await agent(dict(state))
        except AgentError as exc:
            raise HRMultiAgentRuntimeError(agent_name, str(exc)) from exc
        except Exception as exc:
            raise HRMultiAgentRuntimeError(agent_name, str(exc)) from exc
        if not isinstance(updates, dict):
            raise HRMultiAgentRuntimeError(
                agent_name,
                f"invalid update payload type {type(updates).__name__}",
            )
        return updates

    async def run_resume_pipeline(
        self,
        *,
        filename: str,
        content: bytes,
        parsed_job: dict[str, Any],
        job_id: str | None = None,
        candidate_email: str | None = None,
        db: Any | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """
        Full in-process multi-agent resume flow:
          file extraction -> (resume parse + embedding) -> dedup -> scoring
        """
        state: dict[str, Any] = {
            "filename": filename,
            "content": content,
            "file_bytes": content,
            "parsed_job": parsed_job or {},
            "job_id": job_id,
            "candidate_email": candidate_email,
            "db": db,
            "timeout_s": float(timeout_s) if timeout_s is not None else 45.0,
        }

        async def _pipeline() -> dict[str, Any]:
            self._merge_updates(
                state,
                await self.run_agent("file_extraction_agent", state),
            )

            parser_task = self.run_agent("resume_parser_agent", state)
            embed_task = self.run_agent(
                "embedding_agent",
                {**state, "embed_text": state.get("text", "")},
            )
            parser_updates, embed_updates = await asyncio.gather(parser_task, embed_task)
            self._merge_updates(state, parser_updates)
            self._merge_updates(state, embed_updates)

            self._merge_updates(
                state,
                await self.run_agent("deduplication_agent", state),
            )

            self._merge_updates(
                state,
                await self.run_agent("scoring_agent", state),
            )
            return state

        bounded_timeout = float(timeout_s) if timeout_s is not None else None
        if bounded_timeout is not None and bounded_timeout > 0:
            return await asyncio.wait_for(_pipeline(), timeout=bounded_timeout)
        return await _pipeline()

    async def parse_resume(self, text: str) -> dict[str, Any]:
        updates = await self.run_agent("resume_parser_agent", {"text": text})
        parsed = updates.get("parsed_resume")
        if not isinstance(parsed, dict):
            raise HRMultiAgentRuntimeError("resume_parser_agent", "missing parsed_resume")
        return parsed

    async def parse_jd(self, jd_text: str) -> dict[str, Any]:
        updates = await self.run_agent("jd_parser_agent", {"jd_text": jd_text})
        parsed = updates.get("parsed_job")
        if not isinstance(parsed, dict):
            raise HRMultiAgentRuntimeError("jd_parser_agent", "missing parsed_job")
        return parsed

    async def embed_text(self, text: str) -> list[Any]:
        updates = await self.run_agent("embedding_agent", {"embed_text": text})
        embedding = updates.get("embedding")
        if not isinstance(embedding, list):
            return []
        return embedding

    async def generate_jd(
        self,
        *,
        role: str,
        experience_min: int,
        experience_max: int,
        location: str | None = None,
        additional_context: str | None = None,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "jd_generator_agent",
            {
                "role": role,
                "experience_min": int(experience_min),
                "experience_max": int(experience_max),
                "location": location or "Remote",
                "additional_context": additional_context or "",
            },
        )
        jd_data = updates.get("jd_data")
        if not isinstance(jd_data, dict):
            raise HRMultiAgentRuntimeError("jd_generator_agent", "missing jd_data")
        return jd_data

    async def score_resume(
        self,
        *,
        parsed_resume: dict[str, Any],
        job_title: str,
        exp_min: int,
        exp_max: int,
        must_have: list[str],
        good_to_have: list[str],
        description: str,
        jd_embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        parsed_job = {
            "title": job_title,
            "role": job_title,
            "experience_min": int(exp_min),
            "experience_max": int(exp_max),
            "must_have_skills": list(must_have or []),
            "good_to_have_skills": list(good_to_have or []),
            "description": description or "",
            "embedding": list(jd_embedding or []),
        }
        updates = await self.run_agent(
            "scoring_agent",
            {
                "parsed_resume": parsed_resume,
                "parsed_job": parsed_job,
            },
        )
        score = updates.get("score_result")
        if not isinstance(score, dict):
            raise HRMultiAgentRuntimeError("scoring_agent", "missing score_result")
        return score

    async def generate_quiz(
        self,
        *,
        jd_text: str,
        skills: list[str],
        easy: int,
        medium: int,
        hard: int,
        timeout_s: float | None = None,
    ) -> list[dict[str, Any]]:
        updates = await self.run_agent(
            "quiz_agent",
            {
                "operation": "generate",
                "jd_text": jd_text,
                "skills": list(skills or []),
                "easy": int(easy),
                "medium": int(medium),
                "hard": int(hard),
                "timeout_s": float(timeout_s) if timeout_s is not None else 45.0,
            },
        )
        questions = updates.get("questions")
        if not isinstance(questions, list):
            raise HRMultiAgentRuntimeError("quiz_agent", "missing questions")
        return questions

    async def parse_quiz_document(self, doc_text: str) -> list[dict[str, Any]]:
        updates = await self.run_agent(
            "quiz_agent",
            {
                "operation": "parse_document",
                "doc_text": doc_text,
            },
        )
        questions = updates.get("questions")
        if not isinstance(questions, list):
            raise HRMultiAgentRuntimeError("quiz_agent", "missing questions")
        return questions

    async def evaluate_code(
        self,
        *,
        problem_statement: str,
        user_code: str,
        language: str,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "code_evaluation_agent",
            {
                "problem_statement": problem_statement,
                "user_code": user_code,
                "language": language,
            },
        )
        result = updates.get("code_eval_result")
        if not isinstance(result, dict):
            raise HRMultiAgentRuntimeError("code_evaluation_agent", "missing code_eval_result")
        return result

    async def enhance_resume(
        self,
        *,
        resume_text: str,
        job_title: str,
        must_have: list[str],
        good_to_have: list[str],
        job_description: str,
    ) -> dict[str, Any]:
        parsed_resume = await self.parse_resume(resume_text)
        updates = await self.run_agent(
            "resume_enhancer_agent",
            {
                "resume_text": resume_text,
                "parsed_resume": parsed_resume,
                "parsed_job": {
                    "title": job_title,
                    "role": job_title,
                    "must_have_skills": list(must_have or []),
                    "good_to_have_skills": list(good_to_have or []),
                    "description": job_description or "",
                },
            },
        )
        result = updates.get("enhancement_result")
        if not isinstance(result, dict):
            raise HRMultiAgentRuntimeError("resume_enhancer_agent", "missing enhancement_result")
        return result

    async def build_resume(self, *, candidate_data: dict[str, Any], target_role: str) -> dict[str, Any]:
        updates = await self.run_agent(
            "resume_builder_agent",
            {
                "candidate_data": candidate_data,
                "target_role": target_role,
            },
        )
        built = updates.get("built_resume")
        if not isinstance(built, dict):
            raise HRMultiAgentRuntimeError("resume_builder_agent", "missing built_resume")
        return built

    async def generate_cover_letter(
        self,
        *,
        candidate_name: str,
        exp_years: float,
        skills: list[Any],
        work_history: list[Any],
        education: list[Any],
        company_name: str,
        job_title: str,
        must_have: list[str],
        job_description: str,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "cover_letter_agent",
            {
                "candidate_name": candidate_name,
                "company_name": company_name,
                "parsed_resume": {
                    "name": candidate_name,
                    "experience_years": float(exp_years),
                    "skills": skills or [],
                    "work_experience": work_history or [],
                    "education": education or [],
                },
                "parsed_job": {
                    "title": job_title,
                    "role": job_title,
                    "must_have_skills": list(must_have or []),
                    "description": job_description or "",
                },
            },
        )
        cover = updates.get("cover_letter")
        if not isinstance(cover, dict):
            raise HRMultiAgentRuntimeError("cover_letter_agent", "missing cover_letter")
        return cover

    async def analyze_career_path(
        self,
        *,
        candidate_name: str,
        experience_years: float,
        skills: list[Any],
        work_history: list[Any],
        education: list[Any],
        career_breaks: list[Any],
        target_role: str,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "career_analyst_agent",
            {
                "candidate_name": candidate_name,
                "experience_years": float(experience_years),
                "skills": skills or [],
                "work_history": work_history or [],
                "education": education or [],
                "career_breaks": career_breaks or [],
                "target_role": target_role,
            },
        )
        analysis = updates.get("career_analysis")
        if not isinstance(analysis, dict):
            raise HRMultiAgentRuntimeError("career_analyst_agent", "missing career_analysis")
        return analysis

    async def draft_hr_email(
        self,
        *,
        email_type: str,
        candidate_name: str,
        job_title: str,
        resume_score: float,
        quiz_score: float,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "notification_agent",
            {
                "operation": "hr_email_draft",
                "email_type": email_type,
                "candidate_name": candidate_name,
                "job_title": job_title,
                "resume_score": float(resume_score),
                "quiz_score": float(quiz_score),
            },
        )
        draft = updates.get("draft")
        if isinstance(draft, dict):
            return draft
        if isinstance(updates.get("subject"), str) and isinstance(updates.get("body"), str):
            return {"subject": updates["subject"], "body": updates["body"]}
        raise HRMultiAgentRuntimeError("notification_agent", "missing hr email draft")

    async def rank_candidates(
        self,
        *,
        jd: dict[str, Any],
        candidates: list[dict[str, Any]],
        use_lyzr: bool = True,
    ) -> dict[str, Any]:
        updates = await self.run_agent(
            "ranking_agent",
            {
                "jd": jd,
                "candidates": candidates,
                "use_lyzr": bool(use_lyzr),
            },
        )
        ranking_result = updates.get("ranking_result")
        if not isinstance(ranking_result, dict):
            raise HRMultiAgentRuntimeError("ranking_agent", "missing ranking_result")
        return ranking_result

    async def health_all(self) -> dict[str, Any]:
        async def _probe(name: str) -> tuple[str, dict[str, Any]]:
            agent = self._agents[name]
            try:
                return name, await agent.health()
            except Exception as exc:
                return name, {"agent": name, "status": "error", "error": str(exc)}

        pairs = await asyncio.gather(*[_probe(name) for name in self._agents])
        return {name: payload for name, payload in pairs}


hr_multi_agent_runtime = HRMultiAgentRuntime()
