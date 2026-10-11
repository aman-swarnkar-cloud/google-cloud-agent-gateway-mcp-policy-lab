"""Agent Runtime entry point for the MCP Policy Lab."""

import logging

import google.auth
from google.auth.transport import mtls

from agentplatform.frameworks import AdkApp
from google.adk.sessions import InMemorySessionService

from .agent import root_agent


def log_auth_diagnostics():
    """Log authentication metadata without exposing credentials."""

    try:
        credentials, _ = google.auth.default(
            scopes=[
                "https://www.googleapis.com/auth/cloud-platform"
            ]
        )

        backend = root_agent.model.api_client._api_client

        logging.warning(
            "AGENT_AUTH_DIAGNOSTIC "
            "credential_class=%s.%s "
            "aiohttp=%s "
            "google_auth_async=%s "
            "client_certificate_requested=%s "
            "certificate_source_available=%s",
            type(credentials).__module__,
            type(credentials).__name__,
            backend._use_aiohttp(),
            backend._use_google_auth_async(),
            mtls.should_use_client_cert(),
            mtls.has_default_client_cert_source(),
        )

    except Exception as exc:
        logging.warning(
            "AGENT_AUTH_DIAGNOSTIC inspection_failed=%s",
            type(exc).__name__,
        )


log_auth_diagnostics()


app = AdkApp(
    agent=root_agent,
    session_service_builder=InMemorySessionService,
)
