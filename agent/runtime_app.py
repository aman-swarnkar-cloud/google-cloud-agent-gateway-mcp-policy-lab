"""Agent Runtime entry point for the MCP Policy Lab."""
'''
import os

os.environ[
    "GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES"
] = "False"
'''

import logging

import google.auth
from google.auth import _agent_identity_utils
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

        cert, _ = (
            _agent_identity_utils.get_agent_identity_certificate_and_bytes()
        )

        logging.warning(
            "AGENT_BOUND_TOKEN_DIAGNOSTIC "
            "agent_identity_cert_present=%s "
            "bound_token_requested=%s",
            cert is not None,
            (
                _agent_identity_utils.should_request_bound_token(cert)
                if cert is not None
                else False
            ),
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
