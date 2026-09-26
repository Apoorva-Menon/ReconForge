"""Native Gemini model setup for the Google ADK agents."""
import os


def gemini_model(model_name):
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("Set GOOGLE_API_KEY in the project .env to run agent evaluations")
    from google.adk.models import Gemini
    return Gemini(model=model_name)
