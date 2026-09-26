from google.adk.agents import LlmAgent

from app.model import gemini_model
from app.prompts import DIAGNOSIS, EVOLUTION, MEMORY
from app.schemas import DiagnosisResult, EvolutionResult, MemoryResult


def create_agents(model_name):
    return {
        key: LlmAgent(name=name, model=gemini_model(model_name), instruction=prompt,
                      output_schema=schema, include_contents="none", mode="single_turn")
        for key, name, prompt, schema in [
            ("diagnosis", "diagnosis_agent", DIAGNOSIS, DiagnosisResult),
            ("memory", "memory_agent", MEMORY, MemoryResult),
            ("evolution", "upgrader_agent", EVOLUTION, EvolutionResult),
        ]
    }
