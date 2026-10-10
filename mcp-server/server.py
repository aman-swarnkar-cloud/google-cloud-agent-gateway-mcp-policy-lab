from mcp.server.fastmcp import FastMCP

mcp = FastMCP("customer-profile-tools")


CUSTOMERS = {
    "CUST-1001": {
        "customer_id": "CUST-1001",
        "name": "Sample Customer",
        "email": "sample@example.com",
        "tier": "gold",
    }
}


@mcp.tool()
def read_customer_profile(customer_id: str) -> dict:
    """Return a synthetic customer profile."""

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
) -> dict:
    """Simulate a customer profile update."""

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
    mcp.run()