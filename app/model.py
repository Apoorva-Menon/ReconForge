"""OpenAI-backed model factory for Google ADK."""

import os


def build_model():
    """Build an ADK-compatible OpenAI model using the configured model name.

    Verify the installed ADK LiteLLM integration and import path before wiring.
    """
    model_name = os.getenv("OPENAI_MODEL", "openai/gpt-5.6-terra")
    raise NotImplementedError(f"Configure the current ADK OpenAI provider for {model_name!r}")
