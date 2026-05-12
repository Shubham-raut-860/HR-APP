"""
azure_openai_service.py – canonical module name for the AI service layer.

BUG-35 FIX: The service was historically named gemini_service.py when
Google Gemini was the LLM provider. It now exclusively uses Azure OpenAI.
This shim re-exports everything from the original module so that new code
can import from the correctly named module while existing code continues
to work unchanged.

Usage:
    from app.services.azure_openai_service import parse_resume, get_embedding
    # or the legacy alias:
    from app.services.gemini_service import parse_resume, get_embedding
"""
from app.services.gemini_service import *  # noqa: F401,F403
