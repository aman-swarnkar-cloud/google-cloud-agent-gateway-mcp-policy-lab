"""Deploy the Google Cloud Agent Gateway MCP Policy Lab agent."""

import argparse
from pathlib import Path

import agentplatform
from agentplatform import types
from agentplatform._genai.types.common import AgentRuntimeConfig


PROJECT_ID = "genai-research-lab"
REGION = "us-central1"

GATEWAY_RESOURCE = (
    f"projects/{PROJECT_ID}/locations/{REGION}/"
    "agentGateways/mcp-policy-gateway"
)

MCP_URL = (
    "https://customer-profile-mcp-governed-"
    "411006551002.us-central1.run.app/mcp"
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_config():
    """Build and validate Agent Runtime deployment configuration."""

    agent_source = REPOSITORY_ROOT / "agent"

    if not agent_source.is_dir():
        raise FileNotFoundError(
            f"Agent source directory missing: {agent_source}"
        )

    requirements = agent_source / "requirements.txt"

    if not requirements.is_file():
        raise FileNotFoundError(
            f"Requirements file missing: {requirements}"
        )

    config = {
        "display_name": "Customer Profile MCP Policy Lab Agent",

        "description": (
            "Google ADK security reference implementation "
            "demonstrating Agent Identity, Agent Gateway "
            "and MCP tool authorization."
        ),

        "source_packages": [
            "agent"
        ],

        "entrypoint_module": "agent.runtime_app",

        "entrypoint_object": "app",

        "requirements_file": "agent/requirements.txt",

        "agent_framework": "google-adk",

        "identity_type": types.IdentityType.AGENT_IDENTITY,

        "agent_gateway_config": {
            "agent_to_anywhere_config": {
                "agent_gateway": GATEWAY_RESOURCE
            }
        },

        "env_vars": {
            "MCP_URL": MCP_URL,
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            #"GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES": "False",
        },

        "min_instances": 0,
        "max_instances": 1,

        "class_methods": [
            {
                "name": "async_create_session",
                "api_mode": "async",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string"
                        },
                        "session_id": {
                            "type": "string"
                        }
                    },
                    "required": ["user_id"]
                }
            },
            {
                "name": "async_stream_query",
                "api_mode": "async_stream",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string"
                        },
                        "user_id": {
                            "type": "string"
                        },
                        "session_id": {
                            "type": "string"
                        }
                    },
                    "required": [
                        "message",
                        "user_id"
                    ]
                }
            }
        ]
    }

    validated = AgentRuntimeConfig.model_validate(config)

    return validated.model_dump(
        mode="json",
        exclude_none=True
    )


def main():
    parser = argparse.ArgumentParser(
        description="Deploy the MCP Policy Lab agent"
    )

    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Actually create the Agent Runtime deployment"
    )

    args = parser.parse_args()

    config = build_config()

    print("Agent Runtime configuration validated")
    print("Project:", PROJECT_ID)
    print("Region:", REGION)
    print("Agent Identity:", config["identity_type"])
    print("Agent Gateway:", GATEWAY_RESOURCE)

    if not args.deploy:
        print("\nDRY VALIDATION ONLY")
        print("No cloud resources created.")
        return

    client = agentplatform.Client(
        project=PROJECT_ID,
        location=REGION,
        http_options={
            "api_version": "v1beta1"
        }
    )

    print("\nStarting Agent Runtime deployment...")

    remote_agent = client.runtimes.create(
        config=config
    )

    print("\nDeployment completed.")
    print("Resource:", remote_agent.api_resource.name)


if __name__ == "__main__":
    main()
