---
name: tool-mcp-contract-designer
description: "Agent tool contract, function calling, MCP tool, resource, prompt, JSON schema, permissions, idempotency, timeout, and error design. Use when exposing an API, database, file, service, or workflow safely to an agent."
---

# Tool and MCP Contract Designer

Design narrow, typed, observable capabilities that agents can select correctly and invoke safely.

## Scope

Use this skill to define or review the agent-facing contract before implementation. It covers ordinary function-calling tools and Model Context Protocol capabilities.

Do not expose a broad shell, database, filesystem, or administrative API when a narrower task-oriented capability can satisfy the use case.

## Required Inputs

- User goals and expected agent decisions.
- Underlying API, service, data source, or operation.
- Trust boundary, credentials, and permission model.
- Side effects, reversibility, latency, and failure modes.
- Expected call frequency and payload size.

Record the applicable MCP specification date/version and SDK version when MCP is involved. If the target version is unknown, mark it unresolved and avoid version-specific claims.

## Workflow

### 1. Inventory capabilities

List the minimum actions and information needed. Split unrelated capabilities. Combine only operations that are always authorized, validated, and executed together.

### 2. Choose the MCP primitive

- Use a **tool** for an action or parameterized computation.
- Use a **resource** for addressable, read-oriented context.
- Use a **prompt** for a reusable interaction template.
- Keep deterministic validation and authorization in code, not in prompt wording.

### 3. Design for correct selection

Give every capability a distinct name and description covering purpose, when to use it, when not to use it, side effects, and important prerequisites. Remove overlapping tools that force the model to guess.

### 4. Define typed inputs

Use closed schemas where possible. Specify required fields, enums, bounds, formats, defaults, mutually exclusive options, and cross-field invariants. Prefer domain identifiers over unvalidated free text.

### 5. Define typed outputs

Separate machine-readable data from human display text. Include result status, stable identifiers, provenance or timestamps when relevant, and structured pagination or partial-result information.

### 6. Define errors and recovery semantics

Use stable error codes for invalid input, unauthorized, forbidden, not found, conflict, rate limited, timeout, dependency unavailable, and internal failure. State whether retry, correction, fallback, or escalation is appropriate.

### 7. Bound side effects

Specify read-only versus mutating behavior, idempotency key, dry-run support, confirmation requirements, transactional boundary, compensation or rollback, and maximum blast radius.

### 8. Define security and privacy

Apply least privilege, server-side authorization, tenant isolation, output minimization, secret redaction, path and URL restrictions, and audit fields. Tool descriptions are not security controls.

### 9. Define operational behavior

Set timeout, cancellation, concurrency, pagination, payload limits, rate-limit handling, logging fields, metrics, and trace correlation.

### 10. Derive contract tests

Cover valid calls, schema rejection, authorization failure, duplicate mutation, timeout, dependency failure, oversized output, malicious input, and misleading tool-selection scenarios.

## Required Output

Start with the applicable protocol/specification and SDK versions. Then use the primitive-specific contract below.

For a tool provide:

```markdown
## Tool: <name>
- Purpose:
- Use when:
- Do not use when:
- Side effects:
- Authorization:
- Timeout/idempotency:

### Input schema

### Output schema

### Error contract

### Examples
- Valid:
- Invalid:
- Ambiguous selection:

### Contract tests
| Case | Input/precondition | Expected result or error code | Observable oracle |
```

For a resource provide its URI or URI template, MIME/content type, list/read behavior, parameters, authorization, freshness and cache semantics, change-notification behavior, size/pagination limits, errors, and example reads.

For a prompt provide its name, purpose, typed arguments, rendered message roles and structure, trusted/untrusted substitutions, escaping rules, errors, and example rendering.

Every contract test must state an expected result or stable error code and an observable oracle. Also provide a capability catalogue, trust-boundary summary, and MCP server/client mapping when MCP is involved.

## Quality Gates

- Names and descriptions distinguish every capability.
- Schemas reject invalid states at the boundary.
- Authorization is enforced outside the model.
- Mutations are bounded, auditable, and safely repeatable or explicitly non-idempotent.
- Errors tell the caller whether to correct, retry, fallback, or escalate.
- Large or sensitive outputs are minimized and paginated.
- Tests exercise both selection and execution contracts.

## Runtime Boundary

This skill produces contracts and implementation guidance. It does not register tools, start MCP servers, provision credentials, enforce sandboxes, or provide transport. Implement and verify those separately.
