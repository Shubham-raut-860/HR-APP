"""Compiled LangGraph workflows — extended with 3 new pipelines using specialized agents."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import (
    CandidateToolsState,
    HarnessState,
    JDGenerationState,
    QuizGenerationState,
    ResumeAgentState,
    ResumeScreeningState,
)


# ─── Existing graphs (unchanged) ─────────────────────────────────────────────

def build_resume_screening_graph():
    graph = StateGraph(ResumeScreeningState)
    graph.add_node("document_intake_agent", nodes.extract_resume_text)
    graph.add_node("resume_scoring_agent", nodes.compute_resume_data)
    graph.add_edge(START, "document_intake_agent")
    graph.add_edge("document_intake_agent", "resume_scoring_agent")
    graph.add_edge("resume_scoring_agent", END)
    return graph.compile()


def build_jd_generation_graph():
    graph = StateGraph(JDGenerationState)
    graph.add_node("cache_agent_prepare_key", nodes.build_jd_cache_query)
    graph.add_node("llm_extraction_agent_embed", nodes.embed_jd_query)
    graph.add_node("cache_agent_read", nodes.read_jd_cache)
    graph.add_node("llm_extraction_agent_generate", nodes.generate_jd_data)
    graph.add_node("cache_agent_write", nodes.write_jd_cache)
    graph.add_edge(START, "cache_agent_prepare_key")
    graph.add_edge("cache_agent_prepare_key", "llm_extraction_agent_embed")
    graph.add_edge("llm_extraction_agent_embed", "cache_agent_read")
    graph.add_conditional_edges(
        "cache_agent_read",
        nodes.route_jd_cache,
        {"cached": END, "generate": "llm_extraction_agent_generate"},
    )
    graph.add_edge("llm_extraction_agent_generate", "cache_agent_write")
    graph.add_edge("cache_agent_write", END)
    return graph.compile()


def build_quiz_generation_graph():
    graph = StateGraph(QuizGenerationState)
    graph.add_node("quiz_agent", nodes.generate_quiz_data)
    graph.add_edge(START, "quiz_agent")
    graph.add_edge("quiz_agent", END)
    return graph.compile()


def build_candidate_tools_graph():
    graph = StateGraph(CandidateToolsState)
    graph.add_node("enhance_resume", nodes.enhance_resume)
    graph.add_node("build_resume", nodes.build_resume)
    graph.add_conditional_edges(
        START,
        nodes.route_candidate_tool,
        {"enhance_resume": "enhance_resume", "build_resume": "build_resume"},
    )
    graph.add_edge("enhance_resume", END)
    graph.add_edge("build_resume", END)
    return graph.compile()


def build_resume_scoring_agents_graph():
    graph = StateGraph(ResumeAgentState)
    graph.add_node("document_intake", nodes.document_intake_agent)
    graph.add_node("parser", nodes.resume_parser_agent)
    graph.add_node("scoring", nodes.scoring_agent)
    graph.add_edge(START, "document_intake")
    graph.add_edge("document_intake", "parser")
    graph.add_edge("parser", "scoring")
    graph.add_edge("scoring", END)
    return graph.compile()


# ─── New extended graphs using specialized agent nodes ────────────────────────

def build_full_resume_pipeline_graph():
    """
    6-node full resume pipeline:
      file_extraction → resume_parser + embedding (parallel) → dedup → scoring
    Uses HarnessState so all specialized agents share one typed dict.
    """
    from app.agents.specialized import (
        FileExtractionAgent, ResumeParserAgent, EmbeddingAgent,
        DeduplicationAgent, ScoringAgent,
    )

    _fe = FileExtractionAgent()
    _rp = ResumeParserAgent()
    _em = EmbeddingAgent()
    _dd = DeduplicationAgent()
    _sc = ScoringAgent()

    async def _file_extraction(state): return await _fe(state)
    async def _resume_parser(state): return await _rp(state)
    async def _embedding(state): return await _em(state)
    async def _dedup(state): return await _dd(state)
    async def _scoring(state): return await _sc(state)

    graph = StateGraph(HarnessState)
    graph.add_node("file_extraction_agent", _file_extraction)
    graph.add_node("resume_parser_agent", _resume_parser)
    graph.add_node("embedding_agent", _embedding)
    graph.add_node("deduplication_agent", _dedup)
    graph.add_node("scoring_agent", _scoring)

    graph.add_edge(START, "file_extraction_agent")
    # resume_parser and embedding run in sequence here (LangGraph doesn't natively fan out;
    # use HarnessAgent.run_pipeline for true parallelism)
    graph.add_edge("file_extraction_agent", "resume_parser_agent")
    graph.add_edge("resume_parser_agent", "embedding_agent")
    graph.add_edge("embedding_agent", "deduplication_agent")
    graph.add_edge("deduplication_agent", "scoring_agent")
    graph.add_edge("scoring_agent", END)
    return graph.compile()


def build_quiz_with_code_eval_graph():
    """
    Quiz pipeline extended with a code evaluation node:
      quiz_agent(generate) → [quiz submission] → quiz_agent(evaluate) → code_evaluation_agent
    """
    from app.agents.specialized import QuizAgent, CodeEvaluationAgent

    _quiz = QuizAgent()
    _code = CodeEvaluationAgent()

    async def _generate(state): return await _quiz({**state, "operation": "generate"})
    async def _evaluate(state): return await _quiz({**state, "operation": "evaluate"})
    async def _code_eval(state): return await _code(state)

    def _route_code(state) -> str:
        return "code_eval" if state.get("user_code") else "end"

    graph = StateGraph(HarnessState)
    graph.add_node("quiz_generate", _generate)
    graph.add_node("quiz_evaluate", _evaluate)
    graph.add_node("code_evaluation_agent", _code_eval)

    graph.add_edge(START, "quiz_generate")
    graph.add_edge("quiz_generate", "quiz_evaluate")
    graph.add_conditional_edges(
        "quiz_evaluate",
        _route_code,
        {"code_eval": "code_evaluation_agent", "end": END},
    )
    graph.add_edge("code_evaluation_agent", END)
    return graph.compile()


def build_ranking_pipeline_graph():
    """
    Ranking pipeline:
      ranking_agent → notification_agent (notify HR of top picks)
    """
    from app.agents.specialized import RankingAgent, NotificationAgent

    _rank = RankingAgent()
    _notify = NotificationAgent()

    async def _ranking(state): return await _rank(state)
    async def _notify_hr(state):
        top = (state.get("ranking_result") or {}).get("top_pick", "")
        return await _notify({
            **state,
            "operation": "push_hr",
            "title": "Ranking Complete",
            "message": f"Candidates ranked. Top pick: {top}",
            "ntype": "system",
        })

    def _should_notify(state) -> str:
        return "notify" if state.get("notify_on_complete", True) else "skip"

    graph = StateGraph(HarnessState)
    graph.add_node("ranking_agent", _ranking)
    graph.add_node("notification_agent", _notify_hr)

    graph.add_edge(START, "ranking_agent")
    graph.add_conditional_edges(
        "ranking_agent",
        _should_notify,
        {"notify": "notification_agent", "skip": END},
    )
    graph.add_edge("notification_agent", END)
    return graph.compile()


def build_career_tools_graph():
    """
    Candidate career tools graph — routes by operation:
      enhance_resume  → ResumeEnhancerAgent
      build_resume    → ResumeBuilderAgent
      cover_letter    → CoverLetterAgent
      full_career     → ResumeEnhancerAgent + CoverLetterAgent (sequential)
    """
    from app.agents.specialized import ResumeEnhancerAgent, ResumeBuilderAgent, CoverLetterAgent

    _re = ResumeEnhancerAgent()
    _rb = ResumeBuilderAgent()
    _cl = CoverLetterAgent()

    async def _enhance(state): return await _re(state)
    async def _build(state): return await _rb(state)
    async def _cover(state): return await _cl(state)

    def _route(state) -> str:
        op = state.get("operation", "enhance_resume")
        if op in ("enhance_resume", "full_career"): return "enhance"
        if op == "build_resume": return "build"
        if op == "cover_letter": return "cover"
        raise ValueError(f"career_tools: unknown operation '{op}'")

    def _route_after_enhance(state) -> str:
        return "cover" if state.get("operation") == "full_career" else "end"

    graph = StateGraph(HarnessState)
    graph.add_node("enhance_resume", _enhance)
    graph.add_node("build_resume", _build)
    graph.add_node("cover_letter", _cover)

    graph.add_conditional_edges(START, _route, {
        "enhance": "enhance_resume",
        "build": "build_resume",
        "cover": "cover_letter",
    })
    graph.add_conditional_edges("enhance_resume", _route_after_enhance, {
        "cover": "cover_letter",
        "end": END,
    })
    graph.add_edge("build_resume", END)
    graph.add_edge("cover_letter", END)
    return graph.compile()
