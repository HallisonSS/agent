# app/ia/agents.py
from dataclasses import dataclass
from typing import Callable

@dataclass
class Agent:
    name: str
    system_prompt: str
    provider: str          # "ollama" ou "openai"
    tools: dict[str, Callable]

REGISTRY: dict[str, Agent] = {}

def register(agent: Agent):
    REGISTRY[agent.name] = agent
