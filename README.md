# Google Cloud Agent Gateway MCP Policy Lab

A hands-on reference implementation for governing AI agent access to MCP tools using Google Cloud Agent Gateway, Agent Identity, and IAM access policies.

## What this lab demonstrates

An enterprise AI agent may be technically capable of discovering and invoking multiple tools, but that does not mean it should be authorized to use every tool.

This lab explores a simple question:

> **How can we enforce which MCP tools a specific AI agent is allowed to invoke?**

The reference scenario uses two MCP tools:

- `read_customer_profile` — allowed
- `update_customer_profile` — denied

The intended execution path is:

**Agent → Agent Identity → Agent Gateway → MCP Server → Tool**

The goal is to demonstrate that tool access is controlled by an explicit policy boundary rather than relying only on what the agent chooses to call.

## What we will validate

The lab will demonstrate:

1. an agent accessing an MCP server through Agent Gateway,
2. the agent being evaluated as a distinct identity,
3. an allow policy for an approved MCP tool,
4. a deny/restrictive policy for another MCP tool,
5. policy evaluation in dry-run mode,
6. enforcement of the validated policy,
7. evidence showing the allowed and denied outcomes.

## Design principle

> **Tool discovery is not tool authorization.**

An agent may know that a tool exists while still being prevented from invoking it by the runtime authorization layer.

## Scope

This repository is a generic technical lab based on publicly documented Google Cloud capabilities.

It does not represent any customer implementation or production environment.