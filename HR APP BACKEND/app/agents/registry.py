"""Service-to-agent ownership map — updated to include all 14 specialized agents."""

SERVICE_AGENT_MAP: dict[str, dict[str, object]] = {
    "file_extraction_agent": {
        "services": ["file_service", "encryption_service"],
        "functions": ["extract_text", "extract_text_from_bytes", "save_file", "encrypt_file", "decrypt_file"],
        "owns": "File validation, text extraction, storage, and encryption boundaries.",
        "class": "FileExtractionAgent",
    },
    "resume_parser_agent": {
        "services": ["gemini_service"],
        "functions": ["parse_resume"],
        "owns": "Converts raw resume text → structured parsed_resume dict.",
        "class": "ResumeParserAgent",
    },
    "jd_parser_agent": {
        "services": ["gemini_service"],
        "functions": ["parse_jd_from_document"],
        "owns": "Converts raw JD text → structured parsed_job dict.",
        "class": "JDParserAgent",
    },
    "jd_generator_agent": {
        "services": ["gemini_service", "cache_service"],
        "functions": ["generate_jd", "get_embedding", "get_cached_jd", "cache_jd"],
        "owns": "JD generation from role/params with embedding-similarity cache.",
        "class": "JDGeneratorAgent",
    },
    "embedding_agent": {
        "services": ["gemini_service"],
        "functions": ["get_embedding"],
        "owns": "Text → dense vector embedding for semantic search and similarity.",
        "class": "EmbeddingAgent",
    },
    "scoring_agent": {
        "services": ["scoring_service", "gemini_service"],
        "functions": [
            "skill_match_score", "experience_match_score", "project_relevance_score",
            "education_match_score", "location_match_score", "cosine_similarity",
            "compute_resume_score_with_ai_override", "assign_tag", "detect_candidate_tier",
            "score_resume_against_jd",
        ],
        "owns": "Rule-based + AI hybrid resume scoring pipeline.",
        "class": "ScoringAgent",
    },
    "deduplication_agent": {
        "services": [],
        "functions": ["sha256 file_hash", "Candidate.email DB lookup"],
        "owns": "Duplicate candidate detection via file_hash and email per job.",
        "class": "DeduplicationAgent",
    },
    "quiz_agent": {
        "services": ["gemini_service", "scoring_service"],
        "functions": ["generate_quiz_questions", "parse_quiz_from_document", "compute_quiz_score"],
        "owns": "Quiz generation, document parsing, answer evaluation.",
        "class": "QuizAgent",
    },
    "code_evaluation_agent": {
        "services": ["gemini_service"],
        "functions": ["evaluate_code_submission"],
        "owns": "AI code grading with 60-second timeout.",
        "class": "CodeEvaluationAgent",
    },
    "ranking_agent": {
        "services": ["lyzr (httpx)", "scoring_service"],
        "functions": ["Lyzr /match API", "resume_score sort fallback"],
        "owns": "Force-ranks candidates against a JD using Lyzr AI with rule-based fallback.",
        "class": "RankingAgent",
    },
    "resume_enhancer_agent": {
        "services": ["gemini_service", "scoring_service"],
        "functions": ["enhance_resume", "skill_match_score", "semantic_skill_match"],
        "owns": "AI resume enhancement targeting a specific JD.",
        "class": "ResumeEnhancerAgent",
    },
    "resume_builder_agent": {
        "services": ["gemini_service"],
        "functions": ["build_resume_from_form"],
        "owns": "Generates complete ATS-optimised resume from structured form data.",
        "class": "ResumeBuilderAgent",
    },
    "cover_letter_agent": {
        "services": ["gemini_service"],
        "functions": ["generate_cover_letter"],
        "owns": "Personalised cover letter generation for a specific job application.",
        "class": "CoverLetterAgent",
    },
    "notification_agent": {
        "services": ["notification_service", "email_service", "gemini_service"],
        "functions": [
            "push_notification", "push_to_candidate_by_email", "push_to_all_candidates",
            "push_to_hr_users", "send_email_async", "generate_hr_email",
        ],
        "owns": "In-app notifications, SMTP email, and AI-drafted HR emails.",
        "class": "NotificationAgent",
    },
    # ── Harness ────────────────────────────────────────────────────────────────
    "harness_agent": {
        "services": ["all agents above"],
        "functions": ["run", "run_agent", "run_pipeline", "run_parallel", "health_all"],
        "owns": "Master orchestrator — routes tasks, manages pipelines, retries, health probes.",
        "class": "HarnessAgent",
    },
    # ── Legacy entries (retained for backward compat) ─────────────────────────
    "llm_extraction_agent": {
        "services": ["gemini_service"],
        "functions": ["parse_resume", "parse_jd_from_document", "generate_jd", "get_embedding", "normalize_skills"],
        "owns": "LEGACY — superseded by resume_parser_agent + jd_parser_agent + jd_generator_agent + embedding_agent.",
        "class": None,
    },
    "observability_agent": {
        "services": ["mlflow_service", "langfuse_service"],
        "functions": ["tag_trace_with_session", "mlflow_track_llm", "run_mlflow_evaluation"],
        "owns": "Trace tagging, evaluation logging, prompt/model observability.",
        "class": None,
    },
    "auth_policy_agent": {
        "services": ["auth_service"],
        "functions": ["hash_password", "verify_password", "create_access_token", "decode_token", "require_hr", "log_action"],
        "owns": "Identity, role policy, and audit log writes.",
        "class": None,
    },
    "export_agent": {
        "services": ["export_service", "rendercv_service"],
        "functions": ["export_candidates_excel", "export_candidates_pdf", "render_resume_pdf"],
        "owns": "Report and resume document rendering/export.",
        "class": None,
    },
    "cache_agent": {
        "services": ["cache_service"],
        "functions": ["get_cached_jd", "cache_jd"],
        "owns": "Embedding-similarity cache lookups and writes — now inlined into JDGeneratorAgent.",
        "class": None,
    },
}
