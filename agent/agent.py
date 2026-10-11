import asyncio
import os
from functools import lru_cache
from urllib.parse import urlsplit

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import (
    McpToolset,
    StreamableHTTPConnectionParams,
)
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google.adk.models.google_llm import Gemini

MODEL = os.getenv("MODEL", "gemini-3.5-flash")

MCP_URL = os.environ["MCP_URL"]

# Validate the configured MCP destination.
parsed_url = urlsplit(MCP_URL)

if (
    parsed_url.scheme != "https"
    or not parsed_url.netloc
    or parsed_url.username is not None
    or parsed_url.password is not None
    or parsed_url.query
    or parsed_url.fragment
):
    raise ValueError("MCP_URL must be a valid HTTPS endpoint")

# Cloud Run expects the service URL as the token audience.
MCP_AUDIENCE = f"{parsed_url.scheme}://{parsed_url.netloc}"


@lru_cache(maxsize=1)
def get_mcp_credentials():
    """Create and cache Agent Identity OIDC credentials."""
    return id_token.fetch_id_token_credentials(
        audience=MCP_AUDIENCE
    )


def build_auth_headers():
    """Refresh credentials if needed and construct auth headers."""
    headers = {}

    credentials = get_mcp_credentials()

    credentials.before_request(
        Request(),
        "POST",
        MCP_URL,
        headers,
    )

    return headers


async def get_mcp_auth_headers(_context):
    """Provide authenticated headers for MCP requests."""
    return await asyncio.to_thread(build_auth_headers)


customer_profile_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_URL,
    ),
    header_provider=get_mcp_auth_headers,
)


root_agent = Agent(
    name="customer_profile_policy_agent",
    model=Gemini(
        model="gemini-3.8-flash",
        api_version="v1",
        client_kwargs={
            "enterprise": True,
            "location": "global",
        },
    ),
    description=(
        "Demonstrates policy-governed access to customer "
        "profile tools through Google Cloud Agent Gateway."
    ),
    instruction="""
You are a customer-profile assistant operating in a security lab.

All customer information is synthetic.

Available capabilities:

1. read_customer_profile
2. update_customer_profile

Use the appropriate MCP tool when a user requests
customer information or a simulated update.

Do not make authorization decisions yourself.

All authorization decisions are enforced externally
through Google Cloud Agent Gateway and IAM policies.

If a tool invocation is denied, inform the user
that the operation was not authorized.

Never claim that an operation succeeded unless
the downstream MCP tool confirms success.

Do not invent customer information or tool results.
""",
    tools=[customer_profile_tools],
)
