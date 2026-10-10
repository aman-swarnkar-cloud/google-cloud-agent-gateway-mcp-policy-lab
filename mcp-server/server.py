from typing import Any
import os

from mcp.server.mcpserver import MCPServer

# Synthetic data only. No real customer information.
CUSTOMERS = {
    "CUST-1001": {
        "customer_id": "CUST-1001",
        "name": "Sample Customer",
        "email": "sample@example.com",
        "tier": "gold",
    }
}

mcp = MCPServer("customer-profile-tools")


@mcp.tool()
def read_customer_profile(customer_id: str) -> dict[str, Any]:
    """Retrieve a synthetic customer profile."""

    profile = CUSTOMERS.get(customer_id)

    if profile is None:
        return {
            "status": "not_found",
            "customer_id": customer_id,
        }

    return {
        "status": "success",
        "profile": profile,
    }


@mcp.tool()
def update_customer_profile(
    customer_id: str,
    email: str | None = None,
) -> dict[str, Any]:
    """Simulate a customer profile update without modifying data."""

    if customer_id not in CUSTOMERS:
        return {
            "status": "not_found",
            "customer_id": customer_id,
        }

    return {
        "status": "simulated_update",
        "customer_id": customer_id,
        "requested_email": email,
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )
