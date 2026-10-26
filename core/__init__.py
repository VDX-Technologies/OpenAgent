"""Core package — LLM client, agent orchestrator, and memory."""

from core.agent import Agent
from core.llm import OllamaClient
from core.memory import MemoryManager

__all__ = ["Agent", "OllamaClient", "MemoryManager"]
