"""Package init for specialized agents — exports all 14 agent singletons."""
from __future__ import annotations

from app.agents.specialized.file_extraction_agent import FileExtractionAgent
from app.agents.specialized.resume_parser_agent import ResumeParserAgent
from app.agents.specialized.jd_parser_agent import JDParserAgent
from app.agents.specialized.jd_generator_agent import JDGeneratorAgent
from app.agents.specialized.embedding_agent import EmbeddingAgent
from app.agents.specialized.scoring_agent import ScoringAgent
from app.agents.specialized.deduplication_agent import DeduplicationAgent
from app.agents.specialized.quiz_agent import QuizAgent
from app.agents.specialized.code_evaluation_agent import CodeEvaluationAgent
from app.agents.specialized.ranking_agent import RankingAgent
from app.agents.specialized.resume_enhancer_agent import ResumeEnhancerAgent
from app.agents.specialized.resume_builder_agent import ResumeBuilderAgent
from app.agents.specialized.cover_letter_agent import CoverLetterAgent
from app.agents.specialized.notification_agent import NotificationAgent

__all__ = [
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
]
