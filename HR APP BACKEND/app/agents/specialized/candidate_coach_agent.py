"""CandidateCoachAgent - read-only guidance over candidate-owned snapshots."""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent


class CandidateCoachAgent(BaseAgent):
    name = "candidate_coach_agent"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = state.get("snapshot") if isinstance(state.get("snapshot"), dict) else {}
        question = str(state.get("question") or "").strip()
        metrics = snapshot.get("metrics") if isinstance(snapshot.get("metrics"), dict) else {}
        applications = snapshot.get("applications") if isinstance(snapshot.get("applications"), list) else []
        resumes = snapshot.get("resumes") if isinstance(snapshot.get("resumes"), list) else []
        risks = snapshot.get("risks") if isinstance(snapshot.get("risks"), list) else []

        total_applications = int(metrics.get("total_applications") or 0)
        active_applications = int(metrics.get("active_applications") or 0)
        pending_assessments = int(metrics.get("pending_assessments") or 0)
        completed_assessments = int(metrics.get("completed_assessments") or 0)
        vault_resumes = int(metrics.get("vault_resumes") or 0)

        if total_applications == 0:
            headline = "No applications are active yet."
        else:
            headline = (
                f"{active_applications} active application(s), "
                f"{pending_assessments} pending assessment(s), and "
                f"{completed_assessments} completed assessment(s)."
            )

        recommendations: list[str] = []
        if vault_resumes == 0:
            recommendations.append("Upload a resume to the vault so future applications can reuse parsed profile data.")
        if total_applications == 0:
            recommendations.append("Browse open jobs and apply to roles that match your strongest skills.")
        if pending_assessments > 0:
            recommendations.append("Complete pending assessments first; they can materially affect your final ranking.")
        if resumes and not any(item.get("is_default") for item in resumes):
            recommendations.append("Set a default resume so job applications start from the right profile.")
        if risks:
            recommendations.append(risks[0])
        if not recommendations:
            recommendations.append("Keep your resume current and monitor application progress after recruiter updates.")

        latest_application = applications[0] if applications else None
        answer_parts = [headline]
        if latest_application:
            answer_parts.append(
                f"Most recent application: {latest_application.get('job_title') or 'Untitled job'} "
                f"with status {latest_application.get('application_status') or 'active'}."
            )
        if question:
            answer_parts.append("I used only your candidate-owned applications, resumes, and assessment statuses.")

        return {
            "candidate_coach": {
                "answer": " ".join(answer_parts),
                "headline": headline,
                "recommendations": recommendations[:5],
                "applications": applications[:8],
                "resumes": resumes[:5],
                "risks": risks[:5],
                "metrics": metrics,
                "data_scope": snapshot.get("data_scope") or "candidate_owned",
            }
        }
