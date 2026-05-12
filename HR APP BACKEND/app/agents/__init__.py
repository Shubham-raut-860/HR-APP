"""
LangGraph orchestration layer for HireAI — updated with 14 specialized agents + HarnessAgent.
"""

from app.agents.graphs import (
    build_candidate_tools_graph,
    build_career_tools_graph,
    build_full_resume_pipeline_graph,
    build_jd_generation_graph,
    build_quiz_generation_graph,
    build_quiz_with_code_eval_graph,
    build_ranking_pipeline_graph,
    build_resume_scoring_agents_graph,
    build_resume_screening_graph,
)
from app.agents.harness import HarnessAgent
from app.agents.registry import SERVICE_AGENT_MAP
from app.agents.specialized import (
    CodeEvaluationAgent,
    CoverLetterAgent,
    DeduplicationAgent,
    EmbeddingAgent,
    FileExtractionAgent,
    JDGeneratorAgent,
    JDParserAgent,
    NotificationAgent,
    QuizAgent,
    RankingAgent,
    ResumeBuilderAgent,
    ResumeEnhancerAgent,
    ResumeParserAgent,
    ScoringAgent,
)

__all__ = [
    # Harness
    "HarnessAgent",
    # Specialized agents
    "FileExtractionAgent",
    "ResumeParserAgent",
    "JDParserAgent",
    "JDGeneratorAgent",
    "EmbeddingAgent",
    "ScoringAgent",
    "DeduplicationAgent",
    "QuizAgent",
    "CodeEvaluationAgent",
    "RankingAgent",
    "ResumeEnhancerAgent",
    "ResumeBuilderAgent",
    "CoverLetterAgent",
    "NotificationAgent",
    # Registry
    "SERVICE_AGENT_MAP",
    # Original graphs (backward compat)
    "build_candidate_tools_graph",
    "build_jd_generation_graph",
    "build_quiz_generation_graph",
    "build_resume_scoring_agents_graph",
    "build_resume_screening_graph",
    # New graphs
    "build_full_resume_pipeline_graph",
    "build_quiz_with_code_eval_graph",
    "build_ranking_pipeline_graph",
    "build_career_tools_graph",
]
