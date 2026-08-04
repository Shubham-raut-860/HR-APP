from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.a2a import AgentCard, Capability, Skill


@dataclass(frozen=True)
class A2AAgentDefinition:
    agent_id: str
    name: str
    description: str
    skills: tuple[Skill, ...]
    capabilities: tuple[Capability, ...]
    state_contract: dict[str, Any]
    output_keys: tuple[str, ...]
    enabled: bool = True
    visibility: str = "hr"
    side_effects: bool = False


_TEXT_JSON = ("text", "json")
_JSON = ("json",)


EXPOSED_AGENT_DEFINITIONS: dict[str, A2AAgentDefinition] = {
    "resume_parser_agent": A2AAgentDefinition(
        agent_id="resume_parser_agent",
        name="Resume Parser Agent",
        description="Extracts structured candidate profile data from resume text.",
        skills=(
            Skill(
                id="resume.parse",
                name="Parse resume",
                description="Convert resume text into normalized profile, experience, education, and skill fields.",
                tags=["resume", "candidate", "extraction"],
                examples=["Parse this resume into structured candidate data."],
            ),
        ),
        capabilities=(
            Capability(
                name="resume_text_extraction",
                description="Accepts resume text in content or context.text and returns parsed_resume.",
                input_modes=list(_TEXT_JSON),
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required_any": ["content", "context.text", "context.resume_text"]},
        output_keys=("parsed_resume",),
    ),
    "jd_parser_agent": A2AAgentDefinition(
        agent_id="jd_parser_agent",
        name="JD Parser Agent",
        description="Extracts role requirements, skills, and experience ranges from job description text.",
        skills=(
            Skill(
                id="jd.parse",
                name="Parse job description",
                description="Convert job description text into normalized role, skill, and requirement fields.",
                tags=["job-description", "requirements", "extraction"],
                examples=["Parse this job description for must-have and good-to-have skills."],
            ),
        ),
        capabilities=(
            Capability(
                name="jd_requirement_extraction",
                description="Accepts job description text in content or context.jd_text and returns parsed_job.",
                input_modes=list(_TEXT_JSON),
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required_any": ["content", "context.jd_text", "context.job_description"]},
        output_keys=("parsed_job",),
    ),
    "embedding_agent": A2AAgentDefinition(
        agent_id="embedding_agent",
        name="Embedding Agent",
        description="Generates semantic embeddings for normalized resume or job text.",
        skills=(
            Skill(
                id="text.embed",
                name="Embed text",
                description="Create a vector representation for semantic search and matching.",
                tags=["embedding", "semantic-search", "matching"],
                examples=["Embed this role description for similarity matching."],
            ),
        ),
        capabilities=(
            Capability(
                name="text_embedding",
                description="Accepts content or context.embed_text and returns embedding metadata/vector.",
                input_modes=list(_TEXT_JSON),
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required_any": ["content", "context.embed_text", "context.text"]},
        output_keys=("embedding",),
    ),
    "scoring_agent": A2AAgentDefinition(
        agent_id="scoring_agent",
        name="Resume Scoring Agent",
        description="Scores a parsed candidate profile against a parsed job description.",
        skills=(
            Skill(
                id="resume.score",
                name="Score resume",
                description="Compare parsed_resume and parsed_job and return score_result with matching rationale.",
                tags=["screening", "scoring", "matching"],
                examples=["Score this parsed resume against this parsed job."],
            ),
        ),
        capabilities=(
            Capability(
                name="candidate_fit_scoring",
                description="Requires context.parsed_resume and context.parsed_job and returns score_result.",
                input_modes=["json"],
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required": ["context.parsed_resume", "context.parsed_job"]},
        output_keys=("score_result",),
    ),
    "quiz_agent": A2AAgentDefinition(
        agent_id="quiz_agent",
        name="Quiz Agent",
        description="Generates or parses assessment questions from job requirements.",
        skills=(
            Skill(
                id="quiz.generate",
                name="Generate quiz",
                description="Generate role-specific quiz questions from JD text and target skills.",
                tags=["assessment", "quiz", "skills"],
                examples=["Generate a balanced quiz for this backend engineer JD."],
            ),
            Skill(
                id="quiz.parse_document",
                name="Parse quiz document",
                description="Extract quiz questions from uploaded or pasted assessment content.",
                tags=["assessment", "parsing"],
            ),
        ),
        capabilities=(
            Capability(
                name="quiz_generation",
                description="Accepts context.operation=generate with jd_text, skills, and difficulty counts.",
                input_modes=list(_TEXT_JSON),
                output_modes=list(_JSON),
            ),
        ),
        state_contract={
            "operation": "generate | parse_document",
            "generate_required_any": ["content", "context.jd_text"],
            "parse_required_any": ["content", "context.doc_text"],
        },
        output_keys=("questions",),
    ),
    "career_analyst_agent": A2AAgentDefinition(
        agent_id="career_analyst_agent",
        name="Career Analyst Agent",
        description="Produces role-readiness and career-path analysis for candidate profile data.",
        skills=(
            Skill(
                id="career.analyze",
                name="Analyze career path",
                description="Evaluate target-role readiness, gaps, and next steps from candidate profile context.",
                tags=["career", "candidate", "analysis"],
                examples=["Analyze this candidate's readiness for a senior data analyst role."],
            ),
        ),
        capabilities=(
            Capability(
                name="career_path_analysis",
                description="Accepts candidate profile context and returns career_analysis.",
                input_modes=list(_TEXT_JSON),
                output_modes=list(_JSON),
            ),
        ),
        state_contract={
            "recommended": [
                "context.candidate_name",
                "context.experience_years",
                "context.skills",
                "context.work_history",
                "context.education",
                "context.target_role",
            ]
        },
        output_keys=("career_analysis",),
    ),
    "resume_screening_orchestrator": A2AAgentDefinition(
        agent_id="resume_screening_orchestrator",
        name="Resume Screening Orchestrator",
        description="Runs a multi-agent A2A workflow for resume parsing, JD parsing, embedding, and scoring.",
        skills=(
            Skill(
                id="workflow.resume_screening",
                name="Run resume screening workflow",
                description="Coordinate parser, embedding, and scoring agents for a complete resume-to-JD evaluation.",
                tags=["workflow", "screening", "orchestration"],
                examples=["Screen this resume against this job description and return artifacts."],
            ),
        ),
        capabilities=(
            Capability(
                name="multi_agent_resume_screening",
                description="Requires context.resume_text and context.jd_text; returns parsed_resume, parsed_job, embedding metadata, and score_result.",
                input_modes=["json"],
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required": ["context.resume_text", "context.jd_text"]},
        output_keys=("parsed_resume", "parsed_job", "resume_embedding", "jd_embedding", "score_result"),
    ),
    "recruiter_assistant_agent": A2AAgentDefinition(
        agent_id="recruiter_assistant_agent",
        name="Recruiter Assistant Agent",
        description="Summarizes sanitized recruiter pipeline snapshots and recommends next actions.",
        skills=(
            Skill(
                id="recruiter.pipeline_summarize",
                name="Summarize recruiter pipeline",
                description="Analyze recruiter-owned pipeline metrics, risks, jobs, and top candidates.",
                tags=["recruiter", "pipeline", "copilot"],
                examples=["Summarize this sanitized pipeline snapshot and suggest next actions."],
            ),
        ),
        capabilities=(
            Capability(
                name="recruiter_pipeline_copilot",
                description="Requires context.snapshot and optional question; returns recruiter_copilot.",
                input_modes=["json"],
                output_modes=list(_JSON),
            ),
        ),
        state_contract={"required": ["context.snapshot"], "recommended": ["context.question"]},
        output_keys=("recruiter_copilot",),
    ),
}


INTERNAL_ONLY_AGENTS: dict[str, str] = {
    "notification_agent": "Side-effect capable email and notification drafting must remain behind purpose-built HR routes.",
    "ranking_agent": "Ranking changes hiring decision surfaces and needs stricter workflow-level controls.",
    "file_extraction_agent": "Raw document handling can expose sensitive candidate files.",
    "deduplication_agent": "Candidate identity matching should stay inside controlled resume pipelines.",
    "code_evaluation_agent": "Candidate assessment execution remains protected by quiz attempt authorization.",
    "resume_enhancer_agent": "Candidate document mutation is exposed only through candidate-owned workflows.",
    "resume_builder_agent": "Candidate document generation is exposed only through candidate-owned workflows.",
    "cover_letter_agent": "Candidate document generation is exposed only through candidate-owned workflows.",
    "jd_generator_agent": "JD generation remains available through the existing audited JD routes.",
}


def list_agent_definitions(include_internal: bool = False) -> list[A2AAgentDefinition]:
    agents = list(EXPOSED_AGENT_DEFINITIONS.values())
    if not include_internal:
        return agents
    internal = [
        A2AAgentDefinition(
            agent_id=agent_id,
            name=agent_id.replace("_", " ").title(),
            description=reason,
            skills=(),
            capabilities=(),
            state_contract={},
            output_keys=(),
            enabled=False,
            visibility="internal",
        )
        for agent_id, reason in sorted(INTERNAL_ONLY_AGENTS.items())
    ]
    return agents + internal


def get_agent_definition(agent_id: str) -> A2AAgentDefinition | None:
    return EXPOSED_AGENT_DEFINITIONS.get(agent_id)


def build_agent_card(definition: A2AAgentDefinition, base_url: str) -> AgentCard:
    agent_url = f"{base_url.rstrip('/')}/a2a/agents/{definition.agent_id}/message"
    return AgentCard(
        id=definition.agent_id,
        name=definition.name,
        description=definition.description,
        url=agent_url,
        visibility=definition.visibility,  # type: ignore[arg-type]
        enabled=definition.enabled,
        capabilities=list(definition.capabilities),
        skills=list(definition.skills),
        metadata={
            "runtime": "hr_multi_agent_runtime",
            "state_contract": definition.state_contract,
            "output_keys": list(definition.output_keys),
            "side_effects": definition.side_effects,
        },
    )


def build_platform_agent_card(base_url: str) -> AgentCard:
    return AgentCard(
        id="hireai-a2a-orchestrator",
        name="HIREAI A2A Orchestrator",
        description=(
            "A2A compatibility layer for HIREAI's existing HR multi-agent runtime. "
            "It exposes selected low-risk agents through authenticated task and message endpoints."
        ),
        url=f"{base_url.rstrip('/')}/a2a/tasks",
        visibility="public",
        capabilities=[
            Capability(
                name="agent_discovery",
                description="Discover authenticated HIREAI HR agents and their cards.",
                input_modes=["json"],
                output_modes=["json"],
            ),
            Capability(
                name="task_execution",
                description="Create task-scoped agent executions with artifacts and trace metadata.",
                input_modes=["text", "json"],
                output_modes=["json"],
            ),
        ],
        skills=[
            Skill(
                id="hireai.agent_discovery",
                name="Discover HIREAI agents",
                description="Return A2A Agent Cards for safe, exposed HIREAI HR agents.",
                tags=["a2a", "discovery", "hr"],
            )
        ],
        auth_schemes=["bearer for /a2a/*", "public for /.well-known/agent-card.json"],
        metadata={
            "exposed_agents": sorted(EXPOSED_AGENT_DEFINITIONS),
            "internal_only_agents": INTERNAL_ONLY_AGENTS,
        },
    )
