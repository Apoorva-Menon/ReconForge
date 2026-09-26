from google.adk.agents import LlmAgent
from google.genai import types

from app.model import gemini_model
from app.prompts import DIAGNOSIS, EVOLUTION, MEMORY


_GENERATION_CONFIG = types.GenerateContentConfig(
    max_output_tokens=512,
    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
)


def create_agents(model_name):
    return {
        key: LlmAgent(name=name, model=gemini_model(model_name), instruction=prompt,
                      # Gemini's response_schema serializer emits an unsupported
                      # additional_properties field for these Pydantic schemas.
                      # Prompts request JSON; the workflow validates every result
                      # against the strict Pydantic model before using it.
                      generate_content_config=_GENERATION_CONFIG,
                      include_contents="none", mode="single_turn")
        for key, name, prompt in [
            ("diagnosis", "diagnosis_agent", DIAGNOSIS),
            ("memory", "memory_agent", MEMORY),
            ("evolution", "upgrader_agent", EVOLUTION),
        ]
    }
