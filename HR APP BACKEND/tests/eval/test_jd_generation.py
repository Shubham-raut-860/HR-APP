"""
DeepEval tests — JD Generation

Run with:
    deepeval test run tests/eval/test_jd_generation.py

Or:
    pytest tests/eval/test_jd_generation.py -v

Tests cover:
  TestJDGeneration → Answer Relevancy, JD Completeness, JD Clarity
"""

from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.test_case import LLMTestCase


class TestJDGeneration:
    """
    Validates the quality of AI-generated job descriptions.
    """

    @pytest.mark.parametrize("case", [
        {
            "id": "jg-fullstack",
            "user_input": (
                "Create a job description for a Senior Full-Stack Engineer at a fintech "
                "startup. They need React + Node.js experience, 5+ years, knowledge of "
                "financial systems a plus."
            ),
            "generated_jd": (
                "Senior Full-Stack Engineer — FinTech\n\n"
                "About the Role\n"
                "We are looking for an experienced Full-Stack Engineer to join our rapidly "
                "growing fintech platform. You will design and ship features across our "
                "React frontend and Node.js microservices backend.\n\n"
                "Key Responsibilities\n"
                "- Build and maintain scalable REST APIs using Node.js and Express\n"
                "- Develop responsive user interfaces with React and TypeScript\n"
                "- Collaborate with product and design to deliver features end-to-end\n"
                "- Participate in code reviews and maintain > 80% test coverage\n"
                "- Optimise database queries (PostgreSQL) for financial reporting\n\n"
                "Required Skills\n"
                "- 5+ years of full-stack development experience\n"
                "- Proficiency in React, Node.js, and TypeScript\n"
                "- Experience with RESTful APIs and PostgreSQL\n"
                "- Solid understanding of web security best practices\n\n"
                "Preferred Qualifications\n"
                "- Prior experience in financial services or payments\n"
                "- Knowledge of PCI-DSS compliance\n"
                "- Experience with AWS or GCP"
            ),
        },
        {
            "id": "jg-data-engineer",
            "user_input": (
                "Write a JD for a Data Engineer. Must know Apache Spark, dbt, Snowflake. "
                "3+ years. Remote position."
            ),
            "generated_jd": (
                "Data Engineer (Remote)\n\n"
                "Overview\n"
                "We're hiring a Data Engineer to design, build, and optimise our data "
                "infrastructure. You'll work closely with analytics and ML teams to "
                "power data-driven decisions.\n\n"
                "Responsibilities\n"
                "- Build and maintain ELT pipelines using Apache Spark and dbt\n"
                "- Manage and optimise Snowflake data warehouse schemas\n"
                "- Monitor pipeline health and resolve data quality issues\n"
                "- Document data models and transformation logic\n\n"
                "Requirements\n"
                "- 3+ years of data engineering experience\n"
                "- Proficiency with Apache Spark (PySpark preferred)\n"
                "- Hands-on experience with dbt and Snowflake\n"
                "- Strong SQL skills\n"
                "- Remote-first mindset with good async communication skills"
            ),
        },
    ])
    def test_answer_relevancy(self, case: dict, azure_judge):
        from deepeval.metrics import AnswerRelevancyMetric

        metric = AnswerRelevancyMetric(
            threshold=0.7,
            model=azure_judge,
            include_reason=True,
        )
        tc = LLMTestCase(
            input=case["user_input"],
            actual_output=case["generated_jd"],
        )
        assert_test(tc, [metric])

    @pytest.mark.parametrize("case", [
        {
            "id": "jg-complete",
            "user_input": "JD for a DevOps Engineer with Terraform, AWS, CI/CD experience. 4+ years.",
            "generated_jd": (
                "DevOps Engineer\n\n"
                "About the Role\nJoin our platform team to automate infrastructure and "
                "accelerate developer velocity.\n\n"
                "Responsibilities\n"
                "- Manage cloud infrastructure on AWS using Terraform\n"
                "- Build and maintain CI/CD pipelines (GitHub Actions / Jenkins)\n"
                "- Monitor system health and respond to incidents\n"
                "- Collaborate with engineering teams on deployment strategies\n\n"
                "Required Skills\n"
                "- 4+ years in DevOps or SRE roles\n"
                "- Proficiency with Terraform and AWS\n"
                "- Experience with Docker and Kubernetes\n"
                "- Strong scripting skills (Bash, Python)\n\n"
                "Preferred\n"
                "- Experience with Datadog or Grafana\n"
                "- AWS certifications"
            ),
        },
        {
            "id": "jg-incomplete",
            "user_input": "JD for a DevOps Engineer with Terraform, AWS, CI/CD experience.",
            "generated_jd": "We need someone good at DevOps.",   # ← obviously incomplete
        },
    ])
    def test_jd_completeness(self, case: dict, azure_judge):
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams

        metric = GEval(
            name="JD Completeness",
            criteria=(
                "Evaluate whether the generated job description (ACTUAL_OUTPUT) includes "
                "all essential sections: (1) job title, (2) role overview/summary, "
                "(3) key responsibilities with ≥ 3 specific bullet points, "
                "(4) required skills/qualifications, and (5) preferred qualifications "
                "or nice-to-haves. Score 1.0 only if all five sections are present "
                "and non-trivially filled."
            ),
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
            ],
            model=azure_judge,
            threshold=0.7,
        )
        tc = LLMTestCase(
            input=case["user_input"],
            actual_output=case["generated_jd"],
        )
        if case["id"] == "jg-incomplete":
            result = metric.measure(tc)
            assert metric.score < 0.4, (
                f"Incomplete JD should score < 0.4 on completeness, got {metric.score}"
            )
        else:
            assert_test(tc, [metric])

    @pytest.mark.parametrize("jd,should_pass", [
        (
            (
                "Senior Backend Engineer\n\n"
                "We are seeking a skilled engineer to build and maintain our core APIs.\n\n"
                "Responsibilities\n"
                "- Design and implement REST APIs in Python (FastAPI)\n"
                "- Write comprehensive unit and integration tests\n"
                "- Review pull requests and mentor junior engineers\n\n"
                "Requirements\n"
                "- 5+ years of Python backend development\n"
                "- Experience with FastAPI, SQLAlchemy, and PostgreSQL\n"
                "- Strong understanding of REST API design principles"
            ),
            True,
        ),
        (
            (
                "Rockstar Ninja Dev Wanted!!\n"
                "Join our amazing team and do some stuff.\n"
                "Must be a self-starter who can do everything.\n"
                "Competitive salary depending on vibes."
            ),
            False,
        ),
    ])
    def test_jd_clarity(self, jd: str, should_pass: bool, azure_judge):
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCaseParams

        metric = GEval(
            name="JD Clarity",
            criteria=(
                "Assess the writing quality of the job description. It should: "
                "(1) use clear, professional language without buzzwords like 'rockstar' or 'ninja', "
                "(2) list concrete, measurable responsibilities, "
                "(3) specify required years of experience or skill levels, "
                "(4) avoid vague filler phrases ('competitive salary depending on vibes'). "
                "Score 1.0 for high-quality, professional JD text."
            ),
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT],
            model=azure_judge,
            threshold=0.65,
        )
        tc = LLMTestCase(
            input="N/A",   # clarity does not depend on input
            actual_output=jd,
        )
        result = metric.measure(tc)

        if should_pass:
            assert metric.is_successful(), (
                f"Expected clear JD to pass clarity metric (threshold {metric.threshold}), "
                f"but got score {metric.score}. Reason: {metric.reason}"
            )
        else:
            assert not metric.is_successful(), (
                f"Expected vague JD to fail clarity metric, but it passed with score {metric.score}"
            )
