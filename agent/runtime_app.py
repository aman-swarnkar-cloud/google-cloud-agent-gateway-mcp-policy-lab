"""Agent Runtime entry point for the MCP Policy Lab."""

from agentplatform.frameworks import AdkApp

from .agent import root_agent


app = AdkApp(agent=root_agent)
