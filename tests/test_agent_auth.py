"""Unit tests for ADK MCP authentication without Google Cloud access."""

import asyncio
import importlib
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from google.auth.credentials import Credentials


# Configure a synthetic endpoint before importing the agent.
os.environ["MCP_URL"] = "https://example.run.app/mcp"

agent = importlib.import_module("agent.agent")


class FakeCredentials(Credentials):
    """Simulate refreshable Agent Identity credentials."""

    def __init__(self):
        super().__init__()
        self.refresh_count = 0

    def refresh(self, request):
        self.refresh_count += 1
        self.token = f"synthetic-token-{self.refresh_count}"
        self.expiry = datetime.utcnow() + timedelta(hours=1)


class AgentAuthenticationTests(unittest.TestCase):

    def setUp(self):
        agent.get_mcp_credentials.cache_clear()

    def tearDown(self):
        agent.get_mcp_credentials.cache_clear()

    def test_credentials_are_cached_and_refreshed(self):
        credentials = FakeCredentials()

        with patch.object(
            agent.id_token,
            "fetch_id_token_credentials",
            return_value=credentials,
        ) as credential_factory:

            first = agent.build_auth_headers()
            second = agent.build_auth_headers()

            self.assertEqual(
                first["authorization"],
                "Bearer synthetic-token-1",
            )
            self.assertEqual(first, second)
            self.assertEqual(credentials.refresh_count, 1)

            # Simulate token expiration.
            credentials.expiry = datetime.utcnow() - timedelta(seconds=1)

            refreshed = agent.build_auth_headers()

            self.assertEqual(
                refreshed["authorization"],
                "Bearer synthetic-token-2",
            )
            self.assertEqual(credentials.refresh_count, 2)

            credential_factory.assert_called_once_with(
                audience="https://example.run.app"
            )

    def test_authentication_failure_is_not_ignored(self):
        with patch.object(
            agent.id_token,
            "fetch_id_token_credentials",
            side_effect=RuntimeError("Identity unavailable"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Identity unavailable",
            ):
                agent.build_auth_headers()

    def test_async_header_provider(self):
        credentials = FakeCredentials()

        with patch.object(
            agent.id_token,
            "fetch_id_token_credentials",
            return_value=credentials,
        ):
            headers = asyncio.run(
                agent.get_mcp_auth_headers(None)
            )

            self.assertEqual(
                headers["authorization"],
                "Bearer synthetic-token-1",
            )


if __name__ == "__main__":
    unittest.main()
