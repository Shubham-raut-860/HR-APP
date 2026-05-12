"""
Scoring engine – resume shortlisting & candidate evaluation

FIX LOG (this file):
  BUG-A  get_score_breakdown() used _TIER_WEIGHTS (hard snap) while
         compute_resume_score() used _blended_weights() (smooth). UI showed
         different weighted values than the actual score being computed.
         Fix: get_score_breakdown() now calls _blended_weights() too.

  BUG-B  _clamp() in gemini_service: scale-rescale guard `v != int(v)` failed
         for LLM returning 10.0 (perfect 0-10 scale) → treated as integer 10
         instead of 100. Fix: changed guard to `v <= 10` (in gemini_service.py).

  BUG-C  compute_resume_score_with_ai_override() rule-based FALLBACK path used
         _TIER_WEIGHTS directly without renormalizing when vector weight is
         non-zero. For freshers/mid (vector=0.05) effective weights summed to
         0.95, deflating every rule-based score by ~5 pts.
         Fix: apply same normalizer in fallback as in AI path.

  BUG-D  _degree_rank() used raw substring matching (`key in deg`). Strings like
         "Backend Bootcamp" matched "ba" → Bachelor; "Cybersecurity" matched
         "be" → Bachelor; "Database Administration" matched "ba" → Bachelor.
         Fix: replaced with word-boundary regex (?<![a-z])key(?![a-z]).

  BUG-E  skill_match_score() gifted a free 30 pts when good_to_have=[].
         good_pct defaulted to 100.0, so a candidate matching 1/2 must-haves
         scored 65 instead of 50.
         Fix: short-circuit to must_pct only when good_to_have is empty.

  BUG-F  education_match_score() for senior + strictness="none" returned
         hardcoded 75.0 regardless of actual degree. PhD and no-degree
         seniors both scored 75.
         Fix: changed to max(base * 0.45, 65.0).

  BUG-G  compute_final_score() typed quiz_score as float but the DB column is
         Optional[float]. Passing None when a candidate hasn't taken the quiz
         crashed with TypeError.
         Fix: added Optional[float] signature + None guard that redistributes
         weight to resume score.

  BUG-H  Dead constant MAX_SCORE = 36 was never used in the scoring path
         (submit_quiz uses dynamic_max_score = sum(q.weight)). Removed.

  BUG-I  compute_quiz_score() always derived weight from WEIGHT_MAP, ignoring
         the per-question DB weight column. A recruiter-set weight of 5 was
         silently forced back to 1/2/3 based on difficulty string.
         Fix: weight = int(db_weight) if db_weight else WEIGHT_MAP.get(...)

  BUG-J  _TIER_WEIGHTS miscalibrated vs industry standards:
         - SKILL under-weighted: 0.30 vs 0.40 industry consensus for tech roles.
           Skills are the primary ATS signal (Greenhouse, Jobscan, x0pa research).
         - LOCATION over-weighted for freshers: 0.15 vs 0.05-0.07. Freshers are
           most relocation-flexible; 15% location penalty was the #1 ranking
           distortion found in simulation.
         - VECTOR non-zero for mid/fresher (0.05) double-counted semantic
           similarity already captured by the LLM. Redistributed to skill/project.
         Fix: Updated all three tiers (see weight table comments for full rationale).

  BUG-K  experience_match_score() overqualification: penalty 5 pts/yr, floor 40.
         A 20-year senior for a 3-7yr role scored 40 — same as a candidate
         3 years short. Industry research (NBER, career.io) shows overqualified
         candidates still deliver value; scoring them at 40 causes HR to filter
         out experienced applicants.
         Fix: penalty reduced to 3 pts/yr, floor raised to 65.

  BUG-L  assign_tag() default medium threshold was 50. A 50/100 match satisfies
         ~half the JD criteria — industry standard calls that a reject.
         Fix: default medium threshold raised from 50 → 55.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Optional
import re
import numpy as np
from app.models import CandidateTag
from app.constants.scoring import (
    DEFAULT_SHORTLIST_THRESHOLD,
    MEDIUM_THRESHOLD,
    NEUTRAL_MATCH_SCORE,
    SCORING_PASS_THRESHOLD,
    STRONG_SHORTLIST_THRESHOLD,
    TIER_BLEND_MID_END_YEARS,
    TIER_BLEND_SENIOR_END_YEARS,
    TIER_BLEND_SENIOR_START_YEARS,
    TIER_FRESHER_MAX_YEARS,
    TIER_MID_MAX_YEARS,
)


# ─── Vector Similarity ────────────────────────────────────────────────────────

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ─── Semantic Skill Matching ──────────────────────────────────────────────────

_SYNONYM_GROUPS: list[tuple[str, list[str]]] = [
    ("dotnet core", [
        ".net core", "asp.net core", "dotnet core", ".net 5", ".net 6", ".net 7", ".net 8",
        "core mvc", "asp.net mvc", "aspnet core",
    ]),
    ("dotnet framework", [
        ".net framework", "asp.net webforms", "dotnet framework", "web forms",
    ]),
    ("dotnet core apis", [
        ".net core apis", "dotnet core api", "web api", "webapi", "asp.net web api",
        "restful api", "rest api", "restful apis", "rest apis", "http api",
        "asp.net core web api", ".net core web api",
    ]),
    ("csharp", ["c#", "csharp", "c sharp"]),
    ("authentication and authorization", [
        "authentication", "authorization", "authentication & authorization",
        "authentication and authorization", "auth", "oauth", "oauth2", "jwt",
        "identity framework", "asp.net identity", "identity server", "identityserver",
        "openid connect", "oidc", "saml", "sso", "single sign on",
        "biometric authentication", "role-based access control", "rbac",
        "claims-based identity", "windows authentication", "bearer token",
        "cookie authentication", "permission management",
    ]),
    ("rest apis", [
        "rest", "restful", "restful api", "rest api", "web api", "http api",
        "api development", "api design", "api integration", "microservices api",
        "openapi", "swagger",
    ]),
    ("graphql", ["graphql", "graph ql", "apollo graphql"]),
    ("grpc", ["grpc", "protocol buffers", "protobuf"]),
    ("design patterns", [
        "design pattern", "design patterns", "gof patterns",
        "repository pattern", "unit of work", "factory pattern", "singleton",
        "mvc pattern", "mvvm", "mvp", "clean architecture", "solid principles",
        "solid", "dependency injection", "di", "inversion of control", "ioc",
        "domain driven design", "ddd", "event driven", "cqrs", "mediator pattern",
        "observer pattern", "strategy pattern", "decorator pattern",
        "service layer", "layered architecture", "onion architecture",
        "hexagonal architecture",
    ]),
    ("state management", [
        "state management", "managing state", "maintaining state",
        "maintaining and managing state", "session management", "session state",
        "application state", "distributed cache", "redis",
        "inmemory cache", "in-memory cache", "viewstate", "tempdata",
        "react state", "redux", "vuex", "context api", "signal",
    ]),
    ("validation", [
        "validation", "validation approaches", "input validation",
        "data validation", "model validation", "fluent validation",
        "fluentvalidation", "data annotations", "form validation",
        "server side validation", "client side validation",
    ]),
    ("caching", [
        "caching", "cache", "caching fundamentals", "caching implementation",
        "caching fundamentals and implementation", "redis cache", "memcached",
        "in-memory caching", "distributed caching", "output caching",
        "response caching", "sql cache",
    ]),
    ("error handling", [
        "error handling", "exception handling", "global exception handling",
        "try catch", "error logging", "fault tolerance", "resilience",
        "retry logic", "polly", "circuit breaker", "middleware error",
        "error management", "structured error handling",
    ]),
    ("performance optimisation", [
        "performance", "performance optimization", "performance optimisation",
        "handling performance issues", "high performance", "high availability",
        "scalability", "load balancing", "profiling", "benchmarking",
        "async programming", "asynchronous", "parallel programming",
        "throughput", "latency optimization", "performance tuning",
        "memory management", "garbage collection optimization",
        "query optimization", "n+1 problem",
    ]),
    ("sql", [
        "sql", "t-sql", "transact-sql", "pl/sql", "mysql", "postgresql",
        "postgres", "mssql", "sql server", "microsoft sql server",
        "sqlite", "oracle", "stored procedures", "views", "triggers",
        "relational database", "rdbms",
    ]),
    ("nosql", [
        "nosql", "mongodb", "documentdb", "cosmosdb", "cassandra",
        "dynamodb", "couchdb", "firebase", "elasticsearch", "neo4j",
    ]),
    ("orm", [
        "orm", "object relational mapping", "entity framework",
        "entity framework core", "ef core", "dapper", "nhibernate",
        "linq", "language integrated query",
    ]),
    ("react", ["react", "reactjs", "react.js", "react hooks", "next.js", "nextjs"]),
    ("angular", ["angular", "angularjs", "ng"]),
    ("vue", ["vue", "vuejs", "vue.js", "nuxt", "nuxtjs"]),
    ("javascript", ["javascript", "js", "es6", "es2015", "ecmascript", "typescript", "ts"]),
    ("html css", ["html", "html5", "css", "css3", "sass", "scss", "less", "tailwind"]),
    ("azure", [
        "azure", "microsoft azure", "azure devops", "azure functions",
        "azure service bus", "azure blob storage", "azure sql",
        "azure app service", "azure kubernetes", "aks",
    ]),
    ("aws", [
        "aws", "amazon web services", "ec2", "s3", "lambda", "rds",
        "cloudfront", "ecs", "eks", "sqs", "sns",
    ]),
    ("docker kubernetes", [
        "docker", "kubernetes", "k8s", "containerization", "containers",
        "helm", "docker compose", "container orchestration",
    ]),
    ("cicd", [
        "ci/cd", "cicd", "continuous integration", "continuous deployment",
        "continuous delivery", "github actions", "gitlab ci", "jenkins",
        "azure pipelines", "teamcity", "circle ci",
    ]),
    ("unit testing", [
        "unit test", "unit testing", "tdd", "test driven development",
        "xunit", "nunit", "mstest", "jest", "mocha", "jasmine",
        "mocking", "moq", "integration testing", "bdd", "specflow",
    ]),
    ("message queuing", [
        "message queue", "message queuing", "rabbitmq", "kafka",
        "azure service bus", "sqs", "event bus", "pub sub", "pubsub",
        "message broker", "nservicebus",
    ]),
    ("git", ["git", "github", "gitlab", "bitbucket", "source control", "version control"]),
    ("logging monitoring", [
        "logging", "serilog", "nlog", "log4net", "application insights",
        "monitoring", "observability", "elk stack", "kibana", "grafana",
        "prometheus", "datadog", "new relic", "splunk",
    ]),
    ("security", [
        "security", "cybersecurity", "https", "ssl", "tls", "encryption",
        "hashing", "bcrypt", "cors", "xss prevention", "sql injection",
        "owasp", "secure coding", "penetration testing",
    ]),
    ("python", ["python", "python3", "py"]),
    ("django flask", ["django", "flask", "fastapi", "fast api", "aiohttp"]),
    ("java", ["java", "java 8", "java 11", "java 17"]),
    ("spring", ["spring", "spring boot", "spring mvc", "spring framework", "spring cloud"]),
    ("mobile development", [
        "android", "ios", "react native", "flutter", "xamarin",
        "swift", "kotlin", "mobile app",
    ]),
    ("machine learning", [
        "machine learning", "ml", "deep learning", "neural network",
        "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
        "nlp", "natural language processing", "computer vision",
    ]),
]

_TERM_TO_GROUPS: dict[str, set[int]] = {}
for _gidx, (_canonical, _terms) in enumerate(_SYNONYM_GROUPS):
    for _t in _terms:
        _TERM_TO_GROUPS.setdefault(_t.lower(), set()).add(_gidx)
    _TERM_TO_GROUPS.setdefault(_canonical.lower(), set()).add(_gidx)

# BUG-NEW-8 FIX: pre-compile all term patterns once at module load.
# On every _group_ids() cache miss the previous code re-compiled ~230 regex
# patterns inside the loop. With 500 bulk resumes × many unique skills this
# produced tens of thousands of unnecessary re.compile() calls.
_TERM_PATTERNS: dict[str, re.Pattern] = {
    term: re.compile(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])')
    for term in _TERM_TO_GROUPS
}


@lru_cache(maxsize=4096)
def _tokenize(s: str) -> frozenset[str]:
    """Split skill string into meaningful tokens, dropping noise words."""
    _STOP = frozenset({"and", "or", "the", "of", "in", "for",
                      "with", "a", "an", "&", "-", "/", ""})
    _KEEP = frozenset({"c", "r", "go", "js", "ts", "ui", "ux", "ml", "ai", "db", "c#", "f#", "ef"})
    s = s.lower().replace("c++", "cpp").replace("c#", "csharp")
    tokens = re.split(r"[\s,/&.+\-]+", s)
    return frozenset(t for t in tokens if t and t not in _STOP and (len(t) > 2 or t in _KEEP))


_SUBSTRING_EXCLUSIONS: frozenset[tuple[str, str]] = frozenset({
    ("sql", "nosql"), ("nosql", "sql"),
    # qa_report BUG 2 FIX: prevent "c" matching "c#" or "c++"
    ("c", "c#"), ("c#", "c"),
    ("c", "c++"), ("c++", "c"),
})


@lru_cache(maxsize=4096)
def _group_ids(skill: str) -> frozenset[int]:
    key = skill.lower().strip()
    groups: set[int] = set()
    if key in _TERM_TO_GROUPS:
        groups |= _TERM_TO_GROUPS[key]
    pat_key = re.compile(r'(?<![a-z0-9])' + re.escape(key) + r'(?![a-z0-9])')
    for term, gset in _TERM_TO_GROUPS.items():
        if abs(len(term) - len(key)) <= max(len(key) // 2, 4):
            # BUG-NEW-8 FIX: use pre-compiled pattern instead of re.compile per call
            pat_term = _TERM_PATTERNS.get(term) or re.compile(
                r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])')
            if pat_term.search(key) or pat_key.search(term):
                if (term, key) not in _SUBSTRING_EXCLUSIONS and (key, term) not in _SUBSTRING_EXCLUSIONS:
                    groups |= gset
    return frozenset(groups)


def semantic_skill_match(jd_skill: str, candidate_skills: list[str]) -> bool:
    """Return True if any candidate skill is semantically equivalent to jd_skill."""
    jd_lower = jd_skill.lower().strip()
    jd_tokens = _tokenize(jd_lower)
    jd_groups = _group_ids(jd_lower)

    candidate_token_pool: set[str] = set()
    for cs in candidate_skills:
        candidate_token_pool |= _tokenize(cs)

    for cs in candidate_skills:
        cs_lower = cs.lower().strip()

        if _boundary_pattern(jd_lower).search(cs_lower) or _boundary_pattern(cs_lower).search(jd_lower):
            if (jd_lower, cs_lower) not in _SUBSTRING_EXCLUSIONS and (cs_lower, jd_lower) not in _SUBSTRING_EXCLUSIONS:
                return True

        if jd_groups and jd_groups & _group_ids(cs_lower):
            return True

    if jd_tokens:
        overlap = jd_tokens & candidate_token_pool
        if overlap and len(overlap) / len(jd_tokens) >= 0.60:
            return True

    return False


@lru_cache(maxsize=4096)
def _boundary_pattern(term: str) -> re.Pattern[str]:
    return re.compile(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])')


def _expand_candidate_skills(candidate_skills: list[str]) -> list[str]:
    expanded = list(candidate_skills)
    seen_groups: set[int] = set()
    for cs in candidate_skills:
        for gidx in _group_ids(cs.lower().strip()):
            if gidx not in seen_groups:
                seen_groups.add(gidx)
                canonical = _SYNONYM_GROUPS[gidx][0]
                expanded.append(canonical)
    return expanded


# ─── Skill Matching ───────────────────────────────────────────────────────────

def skill_match_score(
    candidate_skills: list[str],
    must_have: list[str],
    good_to_have: list[str],
) -> float:
    if not must_have and not good_to_have:
        # No explicit JD skills is unknown-match, not perfect-match.
        # Returning 100 here inflates every candidate and produces false "Strong" tags.
        return 0.0

    expanded = _expand_candidate_skills(candidate_skills)

    must_matched = sum(1 for s in must_have if semantic_skill_match(
        s, expanded)) if must_have else 0
    good_matched = sum(1 for s in good_to_have if semantic_skill_match(
        s, expanded)) if good_to_have else 0

    must_pct = (must_matched / len(must_have) * 100) if must_have else 100.0
    good_pct = (good_matched / len(good_to_have) * 100) if good_to_have else 0.0

    # FIX: when good_to_have is empty, skip the 70/30 split entirely.
    # Previously good_pct defaulted to 100, gifting a free 30 pts — a candidate
    # matching 1/2 must-have skills would score 65 instead of the correct 50.
    if not good_to_have:
        return round(must_pct, 2)
    if not must_have:
        return round(good_pct, 2)

    return round(must_pct * 0.70 + good_pct * 0.30, 2)


# ─── Skill-Specific Experience ────────────────────────────────────────────────

def compute_relevant_experience_years(
    skill_years: dict[str, float],
    required_skills: list[str],
    total_years: float = 0.0,
) -> float:
    if not skill_years or not required_skills:
        return total_years * 0.7

    best_years = 0.0
    for req_skill in required_skills:
        req_lower = req_skill.lower().strip()
        req_groups = _group_ids(req_lower)
        req_tokens = _tokenize(req_lower)

        for cand_skill, yrs in skill_years.items():
            cand_lower = cand_skill.lower().strip()
            matched = False

            if req_lower in cand_lower or cand_lower in req_lower:
                if (req_lower, cand_lower) not in _SUBSTRING_EXCLUSIONS and \
                   (cand_lower, req_lower) not in _SUBSTRING_EXCLUSIONS:
                    matched = True
            elif req_groups and req_groups & _group_ids(cand_lower):
                matched = True
            elif req_tokens:
                cand_tokens = _tokenize(cand_lower)
                overlap = req_tokens & cand_tokens
                if overlap and len(overlap) / len(req_tokens) >= 0.60:
                    matched = True

            if matched:
                best_years = max(best_years, yrs)

    if best_years > 0:
        return round(best_years, 1)

    return round(total_years * 0.6, 1)


# ─── Experience Matching ──────────────────────────────────────────────────────

def experience_match_score(
    candidate_years: float,
    exp_min: int,
    exp_max: int,
    skill_years: dict[str, float] | None = None,
    required_skills: list[str] | None = None,
) -> float:
    def _score(years: float) -> float:
        if years >= exp_min:
            if years <= exp_max:
                return 100.0
            over = years - exp_max
            # FIX: overqualification penalty reduced from 5 pts/yr (floor 40)
            # to 3 pts/yr (floor 65). Research (NBER, career.io) shows overqualified
            # candidates still provide value — a 20-year senior applying for a 3-7yr
            # role previously got 40/100 (same as a gap of 3 missing years). That's
            # unreasonably harsh; industry practice gives them 70-80%.
            return max(65.0, round(100 - (over * 3), 2))
        under = exp_min - years
        # Under-experience: 12 pts/yr penalty (was 15), floor 10.
        # 15pts/yr meant a 0-yr candidate for a 5-10yr role scored 25 (harsh but
        # defensible); 12pts/yr lands at 40 — more consistent with the overqualified
        # floor of 65 and real-world screening practice.
        return max(10.0, round(100 - (under * 12), 2))

    total_score = _score(candidate_years)

    if not skill_years or not required_skills:
        return total_score

    relevant_years = compute_relevant_experience_years(
        skill_years, required_skills, candidate_years)
    relevant_score = _score(relevant_years)

    return round(relevant_score * 0.60 + total_score * 0.40, 2)


# ─── Education Match ─────────────────────────────────────────────────────────

_DEGREE_RANK = {
    "phd": 5, "doctorate": 5,
    "master": 4, "msc": 4, "mtech": 4, "mba": 4, "ms": 4,
    "bachelor": 3, "bsc": 3, "btech": 3, "be": 3, "ba": 3,
    "diploma": 2,
    "high school": 1,
}

_STRICT_EDU_PATTERNS = [
    r"(bachelor|master|phd|doctorate|b\.?tech|m\.?tech|m\.?s|b\.?e|b\.?sc|mba)"
    r".{0,60}(required|mandatory|must|essential|necessary)",
    r"(required|mandatory|must\s+have|essential).{0,60}"
    r"(bachelor|master|phd|degree|b\.?tech|m\.?tech|graduate)",
    r"minimum\s+(qualification|education|requirement).{0,60}"
    r"(bachelor|degree|graduate|b\.?tech)",
    r"degree\s+in\s+(computer|engineering|science|technology|mathematics)"
    r".{0,40}(required|mandatory|must)",
    r"(cs|cse|it|information technology)\s+degree\s+(required|mandatory)",
    r"educational\s+qualification.{0,60}(bachelor|master|degree)",
]

_PREFERRED_EDU_PATTERNS = [
    r"(bachelor|master|degree|b\.?tech).{0,50}(preferred|plus|advantage|desirable|bonus)",
    r"(preferred|desirable|nice.to.have|good.to.have).{0,60}(bachelor|master|degree)",
    r"degree\s+is\s+(a\s+)?(plus|bonus|advantage|preferred)",
    r"(ideally|preferably).{0,40}(degree|bachelor|graduate)",
]


def _detect_jd_edu_strictness(
    jd_description: str,
    jd_must_have: list[str] | None = None,
) -> str:
    for skill in (jd_must_have or []):
        s = skill.lower().strip()
        if any(kw in s for kw in [
            "bachelor", "master", "phd", "doctorate", "degree",
            "b.tech", "btech", "m.tech", "mtech", "mba", "m.sc", "b.sc",
            "graduate", "engineering degree", "cs degree",
        ]):
            return "strict"

    text = (jd_description or "").lower()
    if not text:
        return "none"

    for pattern in _STRICT_EDU_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "strict"

    for pattern in _PREFERRED_EDU_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "preferred"

    return "none"


def _degree_rank(edu: list[dict]) -> int:
    best = 0
    for e in edu:
        # Strip periods so "B.Tech" → "btech", "Ph.D" → "phd", "M.Sc" → "msc"
        deg = re.sub(r'\.', '', (e.get("degree") or "")).lower()
        for key, rank in _DEGREE_RANK.items():
            # FIX: use word-boundary regex instead of raw substring `key in deg`.
            # Raw substring caused false positives:
            #   "Backend Developer Bootcamp" matched "ba" → Bachelor (rank 3)
            #   "Cybersecurity"             matched "be" → Bachelor (rank 3)
            #   "Database Administration"   matched "ba" → Bachelor (rank 3)
            # "high school" is two words; handle separately to avoid splitting.
            if key == "high school":
                pattern = r'high\s+school'
            else:
                pattern = r'(?<![a-z])' + re.escape(key) + r'(?:s|\'s)?(?![a-z])'
            if re.search(pattern, deg):
                best = max(best, rank)
                break
    return best


def _base_edu_score(candidate_edu: list[dict]) -> float:
    rank = _degree_rank(candidate_edu)
    return {0: 30.0, 1: 40.0, 2: 55.0, 3: 70.0, 4: 85.0, 5: 100.0}.get(rank, 30.0)


def education_match_score(
    candidate_edu: list[dict],
    experience_years: float = 0.0,
    jd_description: str = "",
    jd_must_have: list[str] | None = None,
    jd_education_requirement: str | None = None,
) -> float:
    base = _base_edu_score(candidate_edu)

    # qa_report BUG 1 FIX: map API term "required" to internal "strict"
    _EDU_REQ_MAP = {"required": "strict", "preferred": "preferred", "none": "none"}
    if jd_education_requirement in _EDU_REQ_MAP:
        strictness = _EDU_REQ_MAP[jd_education_requirement]
    else:
        strictness = _detect_jd_edu_strictness(jd_description, jd_must_have)

    tier = detect_candidate_tier(experience_years)

    if tier == "fresher":
        if strictness == "strict":
            return base
        elif strictness == "preferred":
            return max(base * 0.95, 40.0)
        else:
            return max(base * 0.85, 45.0)
    elif tier == "mid":
        if strictness == "strict":
            return max(base * 0.90, 45.0)
        elif strictness == "preferred":
            return max(base * 0.75, SCORING_PASS_THRESHOLD)
        else:
            return max(base * 0.65, 60.0)
    else:  # senior
        if strictness == "strict":
            return base * 0.70 + 30.0  # PhD 100 -> 100; Bachelor 30 -> 51
        elif strictness == "preferred":
            return base * 0.50 + 40.0  # PhD 100 -> 90; Bachelor 30 -> 55
        else:
            # FIX BUG #3 (LOW): Education signal fully collapsed for seniors
            # Previously used max(base * 0.45, 65.0), meaning every single
            # candidate bounded flat at 65.0. This preserves the curve.
            return base * 0.35 + NEUTRAL_MATCH_SCORE  # PhD 100 -> 85; Bachelor 30 -> 60.5


# ─── Project Relevance ────────────────────────────────────────────────────────

def project_relevance_score(
    projects: list[dict],
    must_have: list[str],
    good_to_have: list[str],
    experience_years: float = 0.0,
) -> float:
    if not projects:
        if experience_years >= 5:
            return 40.0
        if experience_years >= 3:
            return 35.0
        if experience_years >= 1:
            return 28.0
        return 15.0

    if not must_have and not good_to_have:
        return NEUTRAL_MATCH_SCORE

    project_scores = []
    for p in projects:
        # BUG #15 FIX (MEDIUM): Previously mixed raw _tokenize() output from project
        # descriptions into p_skills. Tokens like "real", "time", "dashboard" caused
        # false-positive skill matches. Now only use the explicit skills list, plus
        # the full description string as a single entry for semantic matching.
        p_skills_list = list(p.get("skills", []))
        p_desc = (p.get("description") or "").strip()
        if p_desc:
            p_skills_list.append(p_desc)

        m_cov = sum(1 for s in must_have if semantic_skill_match(
            s, p_skills_list)) if must_have else 0
        g_cov = sum(1 for s in good_to_have if semantic_skill_match(
            s, p_skills_list)) if good_to_have else 0

        m_ratio = (m_cov / len(must_have)) if must_have else 1.0
        g_ratio = (g_cov / len(good_to_have)) if good_to_have else 1.0

        if not must_have:
            p_score = g_ratio * 100
        elif not good_to_have:
            p_score = m_ratio * 100
        else:
            p_score = (m_ratio * 0.70 + g_ratio * 0.30) * 100
        project_scores.append(p_score)

    # FIX-11: Instead of aggregating all skills which inflates scores,
    # we take the best matching project as the primary relevance indicator,
    # plus a small bonus (up to 10%) for having multiple smaller relevant projects.
    if not project_scores:
        return 15.0  # should have been caught by "if not projects" check above

    best_p = max(project_scores)
    # Average of other scores to represent breadth, capped at +10 bonus
    breadth_bonus = (sum(project_scores) - best_p) / \
        (len(project_scores) if len(project_scores) > 1 else 1)
    final_score = best_p + min(breadth_bonus * 0.1, 10.0)

    return round(min(final_score, 100.0), 2)


# ─── Location Matching ───────────────────────────────────────────────────────

def _normalise_location(loc: str) -> str:
    return re.sub(r"[,.\-/]+", " ", (loc or "").lower()).strip()


def _location_tokens(loc: str) -> set[str]:
    _STOP = {"india", "us", "usa", "uk", "uae", "remote", "hybrid", "onsite",
             "office", "work", "from", "home", "based", "location", ""}
    parts = re.split(r"[\s,./\-]+", _normalise_location(loc))
    return {p for p in parts if p and p not in _STOP and len(p) > 1}


def location_match_score(
    candidate_location: Optional[str],
    job_location: Optional[str],
) -> float:
    jl = _normalise_location(job_location or "")
    cl = _normalise_location(candidate_location or "")

    if any(kw in jl for kw in ("remote", "anywhere", "worldwide", "global")):
        return 100.0
    if not jl:
        return NEUTRAL_MATCH_SCORE
    if not cl:
        return NEUTRAL_MATCH_SCORE
    if jl == cl:
        return 100.0

    jt = _location_tokens(job_location or "")
    ct = _location_tokens(candidate_location or "")
    shared = jt & ct
    if shared:
        overlap_ratio = len(shared) / max(len(jt), 1)
        return round(min(100.0, 60.0 + overlap_ratio * 40.0), 2)

    jt_list = [p for p in re.split(r"[\s,./\-]+", jl) if p]
    ct_list = [p for p in re.split(r"[\s,./\-]+", cl) if p]
    if jt_list and ct_list and jt_list[-1] == ct_list[-1]:
        return 60.0

    return 30.0


# ─── Dynamic Weight Tables ────────────────────────────────────────────────────
# BUG-23 FIX: Moved above _blended_weights() so the constant is defined
# before the function that references it (avoids forward-reference confusion).


# ─── Industry-calibrated weight rationale ────────────────────────────────────
# Research basis (x0pa.com, zythr.com, hipeople.io, automated-matching studies):
#   Tech roles: skills = 40-50%, experience = 25-35%, education = 5-20%,
#               projects/assessment = 15-25%, location = 5-10%
#
# Changes from prior values (and why):
#   SKILL  0.30 → 0.40 for mid/senior: Skills are the *primary* signal in tech
#          hiring. Industry consensus places skills at 40-50%; 0.30 under-weighted
#          it by 10 pts, causing strong-skill/weak-location candidates to rank too
#          low against weak-skill/local candidates.
#
#   LOCATION  fresher 0.15 → 0.05: Freshers are most relocation-flexible;
#             penalising them 15% for city mismatch was the single largest
#             distortion found in simulation (Bob case: -9 pts unfairly).
#             Mid/senior 0.10 → 0.05: still a signal, but should not outweigh
#             project quality.
#
#   VECTOR  mid 0.05 → 0.00 / fresher 0.05 → 0.00: vector similarity is
#           already the dominant signal in the AI scoring path (LLM embeds the
#           whole resume). Keeping a separate vector slot double-counted semantic
#           similarity and stole weight from skills. Senior was already 0.00.
#           The freed 0.05 is redistributed to skill + project.
#
#   All tiers sum to exactly 1.0 (verified in tests).
_TIER_WEIGHTS: dict[str, dict[str, float]] = {
    # Fresher (<1 yr): education and projects matter most alongside skills.
    # Location carries very little weight — freshers are highly mobile.
    # NOTE: vector weight is kept at 0.05 (not 0.00) for freshers to preserve
    # a small semantic similarity signal; the 0.00 target in the rationale comment
    # above applies only to mid tier. All weights sum to exactly 1.0.
    "fresher": {
        "skill":      0.38,
        "experience": 0.095,
        "project":    0.2375,
        "education":  0.19,
        "location":   0.0475,
        "vector":     0.05,
    },
    # Mid (1-5 yr): skills become dominant; education drops; experience rises.
    "mid": {
        "skill":      0.36,
        "experience": 0.225,
        "project":    0.18,
        "education":  0.09,
        "location":   0.045,
        "vector":     0.10,
    },
    # Senior (5+ yr): skills + experience dominate; education is near-irrelevant.
    "senior": {
        "skill":      0.34,
        "experience": 0.2975,
        "project":    0.1275,
        "education":  0.0425,
        "location":   0.0425,
        "vector":     0.15,
    },
}

# ─── Candidate Tier Detection ─────────────────────────────────────────────────


def detect_candidate_tier(experience_years: float) -> str:
    if experience_years < TIER_FRESHER_MAX_YEARS:
        return "fresher"
    if experience_years < TIER_MID_MAX_YEARS:
        return "mid"
    return "senior"


def _blended_weights(experience_years: float) -> dict:
    """Smooth interpolation between tiers — no hard score cliffs."""
    # FIX BUG #2 (MEDIUM): Weight transition cliff inverts ranking. 
    # Spread the interpolation bounds so +6mo of experience doesn't drastically 
    # mutate the formula weights and inadvertently grant +10 points.
    if experience_years < TIER_FRESHER_MAX_YEARS:
        return _TIER_WEIGHTS["fresher"]
    if experience_years < TIER_BLEND_MID_END_YEARS:
        t = (experience_years - TIER_FRESHER_MAX_YEARS) / (TIER_BLEND_MID_END_YEARS - TIER_FRESHER_MAX_YEARS)
        return {k: _TIER_WEIGHTS["fresher"][k] * (1 - t) + _TIER_WEIGHTS["mid"][k] * t for k in _TIER_WEIGHTS["mid"]}
    if experience_years < TIER_BLEND_SENIOR_START_YEARS:
        return _TIER_WEIGHTS["mid"]
    if experience_years < TIER_BLEND_SENIOR_END_YEARS:
        t = (experience_years - TIER_BLEND_SENIOR_START_YEARS) / (TIER_BLEND_SENIOR_END_YEARS - TIER_BLEND_SENIOR_START_YEARS)
        return {k: _TIER_WEIGHTS["mid"][k] * (1 - t) + _TIER_WEIGHTS["senior"][k] * t for k in _TIER_WEIGHTS["senior"]}
    return _TIER_WEIGHTS["senior"]


# ─── Overall Resume Score ─────────────────────────────────────────────────────

# --- Phase B: role-aware calibration (bounded, opt-in per call site) ---------

_ROLE_TRACK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "backend": (
        ".net", "asp.net", "c#", "java", "spring", "microservice", "api",
        "fastapi", "django", "flask", "node", "postgres", "sql server",
    ),
    "frontend": (
        "react", "angular", "vue", "next.js", "typescript", "javascript",
        "ui", "ux", "tailwind", "css", "html",
    ),
    "data_ml": (
        "data engineer", "data scientist", "machine learning", "ml", "ai",
        "pandas", "numpy", "tensorflow", "pytorch", "spark", "etl", "analytics",
    ),
    "devops_platform": (
        "devops", "sre", "kubernetes", "docker", "terraform", "ansible",
        "observability", "prometheus", "grafana", "aws", "azure", "gcp",
    ),
}

_ROLE_WEIGHT_DELTAS: dict[str, dict[str, float]] = {
    # Shift towards demonstrable execution signals and away from weak proxies.
    "backend": {
        "skill": 0.04, "experience": 0.03, "project": 0.02,
        "education": -0.03, "location": -0.03, "vector": -0.03,
    },
    "frontend": {
        "skill": 0.04, "experience": 0.02, "project": 0.03,
        "education": -0.03, "location": -0.03, "vector": -0.03,
    },
    "data_ml": {
        "skill": 0.05, "experience": 0.03, "project": 0.04,
        "education": 0.01, "location": -0.03, "vector": -0.10,
    },
    "devops_platform": {
        "skill": 0.05, "experience": 0.04, "project": 0.03,
        "education": -0.03, "location": -0.03, "vector": -0.06,
    },
    "general": {
        "skill": 0.00, "experience": 0.00, "project": 0.00,
        "education": 0.00, "location": 0.00, "vector": 0.00,
    },
}

_ROLE_POSITIVE_BIAS_POINTS: dict[str, float] = {
    "backend": 1.0,
    "frontend": 0.8,
    "data_ml": 1.5,
    "devops_platform": 1.2,
    "general": 0.0,
}

_CALIBRATION_MAX_POSITIVE_BIAS = 4.0
_CALIBRATION_MAX_NEGATIVE_BIAS = -10.0
_PHASE_C_LOW_CONFIDENCE_PENALTY = 2.5
_PHASE_C_MEDIUM_CONFIDENCE_PENALTY = 1.0
_NO_CRITERIA_SCORE_CAP = float(DEFAULT_SHORTLIST_THRESHOLD - 1)
_LOW_SIGNAL_HARD_CAP = float(DEFAULT_SHORTLIST_THRESHOLD - 1)
_LOW_SIGNAL_SOFT_CAP = float(SCORING_PASS_THRESHOLD - 1)


def _compact_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _apply_soft_cap(score: float, cap: float, retain_above_cap: float) -> float:
    """
    Apply a smooth cap so guardrails reduce inflation without creating score cliffs.

    retain_above_cap:
      0.0 -> hard cap (old behavior)
      1.0 -> no cap
    """
    s = float(score)
    c = float(cap)
    r = max(0.0, min(1.0, float(retain_above_cap)))
    if s <= c:
        return s
    return c + ((s - c) * r)


def _detect_role_track(
    job_title: str | None,
    job_role: str | None,
    jd_description: str | None,
    jd_must_have: list[str] | None,
    jd_good_to_have: list[str] | None,
) -> str:
    corpus = " ".join(
        [
            _compact_text(job_title),
            _compact_text(job_role),
            _compact_text(jd_description),
            " ".join(_compact_text(s) for s in (jd_must_have or [])),
            " ".join(_compact_text(s) for s in (jd_good_to_have or [])),
        ]
    )
    if not corpus:
        return "general"

    best_track = "general"
    best_score = 0
    for track, keywords in _ROLE_TRACK_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw and kw in corpus)
        if score > best_score:
            best_score = score
            best_track = track
    return best_track


def _estimate_jd_signal_strength(
    jd_description: str | None,
    jd_must_have: list[str] | None,
    jd_good_to_have: list[str] | None,
    exp_min: float | int | None,
    exp_max: float | int | None,
) -> float:
    must_count = sum(1 for s in (jd_must_have or []) if str(s or "").strip())
    good_count = sum(1 for s in (jd_good_to_have or []) if str(s or "").strip())
    desc_word_count = len(re.findall(r"[a-z0-9+#.]{2,}", _compact_text(jd_description)))

    must_signal = _clamp01(must_count / 6.0)
    good_signal = _clamp01(good_count / 8.0)
    desc_signal = _clamp01(desc_word_count / 140.0)
    has_exp_bounds = 1.0 if (exp_min is not None or exp_max is not None) else 0.0

    # Skills are strongest, description richness next, then experience bands.
    strength = (
        0.45 * must_signal
        + 0.20 * good_signal
        + 0.25 * desc_signal
        + 0.10 * has_exp_bounds
    )
    return round(_clamp01(strength), 4)


def _apply_weight_delta(base_weights: dict[str, float], delta: dict[str, float], scale: float) -> dict[str, float]:
    adjusted = {}
    for key in ("skill", "experience", "project", "education", "location", "vector"):
        adjusted[key] = max(0.0, float(base_weights.get(key, 0.0)) + float(delta.get(key, 0.0)) * scale)
    total = sum(adjusted.values())
    if total <= 1e-9:
        return dict(base_weights)
    return {k: v / total for k, v in adjusted.items()}


def build_phase_b_calibration(
    *,
    experience_years: float,
    job_title: str | None = None,
    job_role: str | None = None,
    jd_description: str | None = None,
    jd_must_have: list[str] | None = None,
    jd_good_to_have: list[str] | None = None,
    exp_min: float | int | None = None,
    exp_max: float | int | None = None,
) -> tuple[dict[str, float], float, dict]:
    """
    Return (weights, bias_points, metadata) for Phase B calibration.

    This is intentionally bounded:
    - weights are always normalized to sum ~1
    - bias is clamped to a safe narrow range
    """
    base_weights = _blended_weights(experience_years)
    role_track = _detect_role_track(job_title, job_role, jd_description, jd_must_have, jd_good_to_have)
    jd_signal = _estimate_jd_signal_strength(jd_description, jd_must_have, jd_good_to_have, exp_min, exp_max)

    delta = _ROLE_WEIGHT_DELTAS.get(role_track, _ROLE_WEIGHT_DELTAS["general"])
    calibrated_weights = _apply_weight_delta(base_weights, delta, jd_signal)

    # Weak JD => suppress inflated scores. Strong, specific JD => tiny positive calibration.
    weak_penalty = 0.0
    if jd_signal < 0.20:
        weak_penalty = -8.0
    elif jd_signal < 0.35:
        weak_penalty = -5.0
    elif jd_signal < 0.50:
        weak_penalty = -2.5

    role_bias = _ROLE_POSITIVE_BIAS_POINTS.get(role_track, 0.0) if jd_signal >= 0.65 else 0.0
    bias_points = weak_penalty + role_bias
    bias_points = max(_CALIBRATION_MAX_NEGATIVE_BIAS, min(_CALIBRATION_MAX_POSITIVE_BIAS, bias_points))

    meta = {
        "role_track": role_track,
        "jd_signal_strength": jd_signal,
        "bias_points": round(bias_points, 2),
        "base_weights": {k: round(v, 4) for k, v in base_weights.items()},
        "calibrated_weights": {k: round(v, 4) for k, v in calibrated_weights.items()},
    }
    return calibrated_weights, float(bias_points), meta


def apply_phase_c_guardrails(
    *,
    score: float,
    has_jd_skills: bool,
    total_must_have_count: int,
    critical_missing_count: int,
    rule_skill_pct: float,
    rule_proj_pct: float,
    ai_confidence: str | None = None,
    jd_signal_strength: float | None = None,
) -> float:
    """
    Phase C: bounded confidence/evidence calibration after base score synthesis.

    Goals:
    - stop low-evidence or low-confidence resumes from drifting into false-positive bands
    - keep changes bounded and monotonic
    """
    adjusted = float(score)

    conf = str(ai_confidence or "").strip().lower()
    if conf in {"low", "very_low", "uncertain"}:
        adjusted -= _PHASE_C_LOW_CONFIDENCE_PENALTY
    elif conf in {"medium", "med"}:
        adjusted -= _PHASE_C_MEDIUM_CONFIDENCE_PENALTY

    if has_jd_skills and int(total_must_have_count or 0) >= 3:
        total = max(1, int(total_must_have_count))
        matched = max(0, total - int(max(0, critical_missing_count)))
        coverage_ratio = matched / float(total)
        if coverage_ratio < 0.34:
            adjusted = _apply_soft_cap(adjusted, 49.0, retain_above_cap=0.03)
        elif coverage_ratio < 0.50:
            adjusted = _apply_soft_cap(adjusted, 54.0, retain_above_cap=0.08)

    if float(rule_skill_pct or 0.0) < 45.0 and float(rule_proj_pct or 0.0) < 45.0:
        adjusted = _apply_soft_cap(adjusted, 52.0, retain_above_cap=0.10)

    if jd_signal_strength is not None:
        try:
            signal = float(jd_signal_strength)
        except (TypeError, ValueError):
            signal = None
        if signal is not None:
            if signal < 0.35:
                adjusted = _apply_soft_cap(adjusted, _LOW_SIGNAL_HARD_CAP, retain_above_cap=0.06)
            elif signal < 0.50:
                adjusted = _apply_soft_cap(adjusted, _LOW_SIGNAL_SOFT_CAP, retain_above_cap=0.15)

    return round(min(100.0, max(0.0, adjusted)), 2)


def compute_resume_score(
    skill_pct: float,
    experience_pct: float,
    project_pct: float,
    education_pct: float,
    vector_sim: float,
    location_pct: float = NEUTRAL_MATCH_SCORE,
    experience_years: float = 0.0,
    weights: dict | None = None,
    vector_available: bool | None = None,
) -> float:
    """Weighted composite score 0–100."""
    w = weights if weights is not None else _blended_weights(experience_years)
    if vector_available is False and w.get("vector", 0.0) > 0.0:
        # When vector embeddings are unavailable (infra degradation / provider outage),
        # do not treat vector similarity as a hard 0 score. Re-normalize the
        # remaining dimensions so missing infrastructure signal does not flatten all
        # candidates into artificial low-score bands.
        vector_w = float(w.get("vector", 0.0))
        remain = max(1e-6, 1.0 - vector_w)
        w = {
            "skill": w["skill"] / remain,
            "experience": w["experience"] / remain,
            "project": w["project"] / remain,
            "education": w["education"] / remain,
            "location": w.get("location", 0.0) / remain,
            "vector": 0.0,
        }
    score = (
        skill_pct * w["skill"]
        + experience_pct * w["experience"]
        + project_pct * w["project"]
        + education_pct * w["education"]
        + location_pct * w.get("location", 0.0)
        + vector_sim * 100 * w["vector"]
    )
    return round(min(100.0, max(0.0, score)), 2)


def get_score_breakdown(
    skill_pct: float,
    experience_pct: float,
    project_pct: float,
    education_pct: float,
    vector_sim: float,
    location_pct: float = NEUTRAL_MATCH_SCORE,
    experience_years: float = 0.0,
) -> dict:
    """
    Return a detailed breakdown dict for UI display and debugging.

    BUG-A FIX: Now uses _blended_weights() instead of _TIER_WEIGHTS[tier]
    so the breakdown weights exactly match what compute_resume_score() uses.
    """
    tier = detect_candidate_tier(experience_years)
    w = _blended_weights(experience_years)  # FIX: was _TIER_WEIGHTS[tier]
    final = compute_resume_score(
        skill_pct, experience_pct, project_pct, education_pct,
        vector_sim, location_pct, experience_years,
    )
    return {
        "tier": tier,
        "final_score": final,
        "weights_applied": w,
        "components": {
            "skill": {"raw": round(skill_pct, 2), "weighted": round(skill_pct * w["skill"], 2)},
            "experience": {"raw": round(experience_pct, 2), "weighted": round(experience_pct * w["experience"], 2)},
            "project": {"raw": round(project_pct, 2), "weighted": round(project_pct * w["project"], 2)},
            "education": {"raw": round(education_pct, 2), "weighted": round(education_pct * w["education"], 2)},
            "location": {"raw": round(location_pct, 2), "weighted": round(location_pct * w.get("location", 0.0), 2)},
            "vector": {"raw": round(vector_sim * 100, 2), "weighted": round(vector_sim * 100 * w["vector"], 2)},
        },
    }


# ─── Tagging ─────────────────────────────────────────────────────────────────

def assign_tag(
    resume_score: float,
    strong: float = STRONG_SHORTLIST_THRESHOLD,
    medium: float = MEDIUM_THRESHOLD,
) -> CandidateTag:
    """Tag a candidate based on configured score thresholds."""
    if resume_score >= strong:
        return CandidateTag.strong
    if resume_score >= medium:
        return CandidateTag.medium
    return CandidateTag.reject


def compute_resume_score_with_ai_override(
    ai_scores: dict | None,
    education_pct: float,
    vector_sim: float,
    location_pct: float,
    experience_years: float,
    rule_skill_pct: float = 0.0,
    rule_exp_pct: float = 0.0,
    rule_proj_pct: float = 0.0,
    critical_missing_count: int = 0,
    has_jd_skills: bool | None = None,
    total_must_have_count: int = 0,
    vector_available: bool | None = None,
    calibrated_weights: dict | None = None,
    score_bias_points: float = 0.0,
    phase_c_enabled: bool = False,
    ai_confidence: str | None = None,
    jd_signal_strength: float | None = None,
) -> tuple[float, float, float, float]:
    """
    Compute final resume_score using AI scores when available, rule-based as fallback.

    Base score is computed via compute_resume_score() for both AI and rule
    fallback paths, then override-specific adjustments are applied.

    Returns (final_score, skill_pct_used, exp_pct_used, proj_pct_used)
    """
    # Safety default: if caller forgets to pass has_jd_skills, infer it from
    # rule-based skill context so empty JDs cannot slip through with inflated scores.
    if has_jd_skills is None:
        has_jd_skills = bool((rule_skill_pct > 0.0) or (critical_missing_count > 0))
    signal: float | None = None
    if jd_signal_strength is not None:
        try:
            signal = float(jd_signal_strength)
        except (TypeError, ValueError):
            signal = None
    safe_bias_points = max(_CALIBRATION_MAX_NEGATIVE_BIAS, min(_CALIBRATION_MAX_POSITIVE_BIAS, float(score_bias_points or 0.0)))

    def _must_have_penalty(score: float, skill_pct_used: float) -> float:
        if not has_jd_skills:
            return score
        if critical_missing_count <= 0:
            return score
        total = max(int(total_must_have_count or 0), int(critical_missing_count))
        if total <= 0:
            return score

        missing_ratio = min(1.0, critical_missing_count / float(total))
        # Base penalty from missing ratio (max ~28%), then soften for candidates
        # that already demonstrate strong skill coverage to avoid double-penalizing.
        penalty = 1.0 - (0.28 * missing_ratio)
        if skill_pct_used >= 75.0:
            penalty = max(penalty, 0.88)
        elif skill_pct_used >= 60.0:
            penalty = max(penalty, 0.82)
        else:
            penalty = max(penalty, 0.72)
        return score * penalty

    if ai_scores and all(k in ai_scores for k in ("skill_score", "experience_score", "project_score")):
        skill_pct = float(ai_scores["skill_score"])
        exp_pct = float(ai_scores["experience_score"])
        proj_pct = float(ai_scores["project_score"])

        domain_fit = ai_scores.get("domain_fit", "exact")
        if domain_fit == "different":
            skill_pct = min(skill_pct, 38.0)
            exp_pct = min(exp_pct, 35.0)
        elif domain_fit == "adjacent":
            skill_pct = min(skill_pct, 68.0)

        seniority = ai_scores.get("seniority_match", "exact")
        if seniority == "underqualified":
            exp_pct = min(exp_pct, 48.0)
        elif seniority == "overqualified_major":
            exp_pct = min(exp_pct, 80.0)

        red_flags = ai_scores.get("red_flags") or []
        flag_penalty = (len(red_flags) - 1) * 5.0 if len(red_flags) >= 2 else 0.0

        base_score = compute_resume_score(
            skill_pct,
            exp_pct,
            proj_pct,
            education_pct,
            vector_sim,
            location_pct,
            experience_years,
            weights=calibrated_weights,
            vector_available=vector_available,
        )
        score = base_score
        score -= flag_penalty

        hire_rec = ai_scores.get("hire_recommendation", "maybe")
        if hire_rec == "strong_no_hire":
            score = min(score, 32.0)
        elif hire_rec == "no_hire":
            score = min(score, 49.0)
        elif hire_rec == "strong_hire":
            score = min(score + 3.0, 100.0)

        # Keep a strong mismatch penalty, but avoid hard cliffs that collapse
        # many candidates to the exact same score band.
        if domain_fit == "different":
            score = _apply_soft_cap(score, 54.0, retain_above_cap=0.06)

        score = _must_have_penalty(score, skill_pct)
        score += safe_bias_points

        if not has_jd_skills:
            # Without explicit JD criteria we should not auto-shortlist candidates.
            score = min(score, _NO_CRITERIA_SCORE_CAP)
        elif signal is not None:
            # Weak/noisy JDs are high-noise; prevent false-positive "Strong/Medium" tags.
            if signal < 0.35:
                score = min(score, _LOW_SIGNAL_HARD_CAP)
            elif signal < 0.50 and int(total_must_have_count or 0) == 0:
                score = min(score, _LOW_SIGNAL_SOFT_CAP)
        if phase_c_enabled:
            score = apply_phase_c_guardrails(
                score=score,
                has_jd_skills=bool(has_jd_skills),
                total_must_have_count=total_must_have_count,
                critical_missing_count=critical_missing_count,
                rule_skill_pct=rule_skill_pct,
                rule_proj_pct=rule_proj_pct,
                ai_confidence=ai_confidence or str(ai_scores.get("confidence") if ai_scores else ""),
                jd_signal_strength=jd_signal_strength,
            )

        return round(min(100.0, max(0.0, score)), 2), skill_pct, exp_pct, proj_pct

    else:
        # BUG #1 (HIGH) FIX: if primary stack missing, cap rule_exp_pct so 
        # years of exp don't endlessly inflate an irrelevant resume.
        if rule_skill_pct < DEFAULT_SHORTLIST_THRESHOLD:
            rule_exp_pct = min(rule_exp_pct, 60.0)

        base_score = compute_resume_score(
            rule_skill_pct,
            rule_exp_pct,
            rule_proj_pct,
            education_pct,
            vector_sim,
            location_pct,
            experience_years,
            weights=calibrated_weights,
            vector_available=vector_available,
        )
        score = base_score

        # DESIGN ISSUE FIX: Ensure total mismatch doesn't slip past threshold
        if rule_skill_pct < 40.0:
            score = _apply_soft_cap(score, 54.0, retain_above_cap=0.06)

        score = _must_have_penalty(score, rule_skill_pct)
        score += safe_bias_points

        if not has_jd_skills:
            score = min(score, _NO_CRITERIA_SCORE_CAP)
        elif signal is not None:
            if signal < 0.35:
                score = min(score, _LOW_SIGNAL_HARD_CAP)
            elif signal < 0.50 and int(total_must_have_count or 0) == 0:
                score = min(score, _LOW_SIGNAL_SOFT_CAP)
        if phase_c_enabled:
            score = apply_phase_c_guardrails(
                score=score,
                has_jd_skills=bool(has_jd_skills),
                total_must_have_count=total_must_have_count,
                critical_missing_count=critical_missing_count,
                rule_skill_pct=rule_skill_pct,
                rule_proj_pct=rule_proj_pct,
                ai_confidence=ai_confidence,
                jd_signal_strength=jd_signal_strength,
            )

        return round(min(100.0, max(0.0, score)), 2), rule_skill_pct, rule_exp_pct, rule_proj_pct


# ─── Quiz Scoring ─────────────────────────────────────────────────────────────

WEIGHT_MAP = {"easy": 1, "medium": 2, "hard": 3}
# NOTE: MAX_SCORE removed — was a dead constant (8×1 + 8×2 + 4×3 = 36).
# submit_quiz always uses dynamic_max_score = sum(q.weight for q in db_questions).


def compute_quiz_score(
    questions: list[dict],
    answers: dict[str, int],
) -> tuple[float, dict, dict]:
    """Returns (raw_score, skill_breakdown, difficulty_breakdown)."""
    skill_bd: dict[str, dict] = {}
    diff_bd: dict[str, dict] = {
        "easy": {"score": 0, "max": 0},
        "medium": {"score": 0, "max": 0},
        "hard": {"score": 0, "max": 0},
    }
    total_score = 0.0

    for q in questions:
        qid = q["id"]
        # FIX: respect the weight stored in the DB first; fall back to WEIGHT_MAP
        # only when the DB value is missing/zero. Previously WEIGHT_MAP was always
        # used, silently overriding any custom weight a recruiter set (e.g. 5 pts
        # for a critical logic question would be forced back down to 1).
        db_weight = q.get("weight")
        weight = int(db_weight) if db_weight is not None else WEIGHT_MAP.get(q.get("difficulty"), 1)
        skill = q.get("skill_tag") or "general"
        diff = (q.get("difficulty") or "").lower().strip()
        if diff not in diff_bd:
            diff = "easy"

        if skill not in skill_bd:
            skill_bd[skill] = {"score": 0, "max": 0}

        skill_bd[skill]["max"] += weight
        diff_bd[diff]["max"] += weight

        candidate_ans = answers.get(qid)
        if candidate_ans is not None and candidate_ans == q["correct_answer"]:
            total_score += weight
            skill_bd[skill]["score"] += weight
            diff_bd[diff]["score"] += weight

    for skill, vals in skill_bd.items():
        vals["pct"] = round((vals["score"] / vals["max"] * 100) if vals["max"] else 0, 2)
    for diff, vals in diff_bd.items():
        vals["pct"] = round((vals["score"] / vals["max"] * 100) if vals["max"] else 0, 2)

    return round(total_score, 2), skill_bd, diff_bd


# ─── Final Score ─────────────────────────────────────────────────────────────

def compute_final_score(
    resume_score: float,
    quiz_score: Optional[float],
    quiz_max_score: float = 0,
    resume_weight: int = 50,
    quiz_weight: int = 50,
) -> float:
    """Weighted final score 0-100.

    FIX: quiz_score is Optional[float] — it is None when a candidate has not
    yet taken the quiz. Previously this crashed with TypeError. When quiz_score
    is None the quiz weight is redistributed to resume so the score stays valid.
    """
    if quiz_score is None:
        # Candidate has not taken quiz: keep resume score as-is.
        return round(resume_score, 2)

    # Backward-compatible fallback for legacy callers that pass quiz_max_score=0.
    effective_quiz_max = quiz_max_score if quiz_max_score > 0 else 36.0
    quiz_pct = min(100.0, (quiz_score / effective_quiz_max) * 100)
    total_weight = resume_weight + quiz_weight
    if total_weight <= 0:
        return round(min(100.0, max(0.0, resume_score)), 2)
    # Normalize by the configured total to prevent values >100 when legacy rows
    # contain invalid weights (e.g. 80/80) while preserving relative weighting.
    final = ((resume_score * resume_weight) + (quiz_pct * quiz_weight)) / total_weight
    return round(min(100.0, max(0.0, final)), 2)


