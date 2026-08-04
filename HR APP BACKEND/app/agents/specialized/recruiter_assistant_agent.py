"""RecruiterAssistantAgent - deterministic copilot over sanitized pipeline snapshots."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent


class RecruiterAssistantAgent(BaseAgent):
    name = "recruiter_assistant_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = state.get("snapshot") if isinstance(state.get("snapshot"), dict) else {}
        question = str(state.get("question") or "").strip()
        metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        jobs = snapshot.get("jobs") if isinstance(snapshot.get("jobs"), list) else []
        top_candidates = snapshot.get("top_candidates") if isinstance(snapshot.get("top_candidates"), list) else []
        risks = snapshot.get("risks") if isinstance(snapshot.get("risks"), list) else []

        total_jobs = int(metrics.get("total_jobs") or 0)
        active_jobs = int(metrics.get("active_jobs") or 0)
        total_candidates = int(metrics.get("total_candidates") or 0)
        strong = int(metrics.get("strong_candidates") or 0)
        medium = int(metrics.get("medium_candidates") or 0)
        untagged = int(metrics.get("untagged_candidates") or 0)
        completed_assessments = int(metrics.get("completed_assessments") or 0)

        headline = (
            f"{active_jobs} active job(s), {total_candidates} candidate(s), "
            f"{strong} strong match(es), and {completed_assessments} completed assessment(s)."
        )
        if total_jobs == 0:
            headline = "No recruiter-owned jobs are available yet."

        recommendations: list[str] = []
        if total_jobs == 0:
            recommendations.append("Create and publish the first job description before reviewing candidates.")
        if active_jobs > 0 and total_candidates == 0:
            recommendations.append("Upload resumes or share the active job links to start building the pipeline.")
        if strong > 0 and completed_assessments == 0:
            recommendations.append("Generate an assessment for strong candidates so ranking includes quiz evidence.")
        if untagged > 0:
            recommendations.append(f"Review {untagged} untagged candidate(s) so the pipeline is easier to triage.")
        if medium > strong and total_candidates > 0:
            recommendations.append("Inspect medium-fit candidates for missing must-have skills before shortlisting.")
        if not recommendations:
            recommendations.append("Continue monitoring new applications and completed assessments.")

        focus_jobs = [
            {
                "id": job.get("id"),
                "title": job.get("title"),
                "candidate_count": job.get("candidate_count", 0),
                "strong_candidates": job.get("strong_candidates", 0),
                "completed_assessments": job.get("completed_assessments", 0),
            }
            for job in jobs[:5]
        ]

        answer_parts = [headline]
        if top_candidates:
            names = ", ".join(str(c.get("name") or "Candidate") for c in top_candidates[:3])
            answer_parts.append(f"Top visible candidates: {names}.")
        if risks:
            answer_parts.append(f"Watch item: {risks[0]}")
        if question:
            answer_parts.append("I used current recruiter-owned jobs and candidates only; no cross-recruiter data is included.")

        return {
            "recruiter_copilot": {
                "answer": " ".join(answer_parts),
                "headline": headline,
                "recommendations": recommendations[:5],
                "focus_jobs": focus_jobs,
                "top_candidates": top_candidates[:5],
                "risks": risks[:5],
                "metrics": metrics,
                "data_scope": snapshot.get("data_scope") or "recruiter_owned",
            }
        }
