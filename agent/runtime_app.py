"""Agent Runtime entry point for the MCP Policy Lab.

Uses in-memory sessions for single-request integration testing.
Managed session authentication will be validated separately.
"""

from agentplatform.frameworks import AdkApp
from google.adk.sessions import InMemorySessionService

from .agent import root_agent


app = AdkApp(
    agent=root_agent,
    session_service_builder=InMemorySessionService,
)
