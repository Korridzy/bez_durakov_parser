---
name: inter-agent-protocol-designer
description: "Inter-agent communication, A2A, agent handoff, message schema, artifact exchange, correlation, provenance, acknowledgement, timeout, idempotency, and protocol versioning. Use ONLY when the primary deliverable is the message, artifact, delivery, and compatibility contract between agents."
---

# Inter-Agent Protocol Designer

Define what agents exchange and how each exchange is interpreted. Keep protocol semantics independent of any particular transport or framework.

## Scope

Use this skill after roles and topology are known. `multi-agent-topology-designer` defines participants, authority, and edges; `agentic-control-flow-designer` defines temporal stages and joins; `agent-recovery-state-machine` defines workflow recovery; `resource-aware-dispatch-designer` defines resource allocation. This skill defines the data exchanged on the edges.

## Required Inputs

- Participating agents and their responsibilities.
- Communication edges and expected interaction sequences.
- Shared artifacts, state ownership, and trust boundaries.
- Delivery, latency, privacy, and audit requirements.
- Existing A2A, MCP, queue, HTTP, or in-process constraints.

## Workflow

### 1. Define protocol participants

Give each participant a stable identity, capability declaration, authority scope, supported protocol versions, and authentication assumptions. Do not infer authorization from an agent's display name.

### 2. Define the common envelope

At minimum consider:

- Protocol version and message type.
- Message, conversation, task, and correlation identifiers.
- Sender, intended recipient, and delegated authority.
- Creation time, expiry, and priority.
- Payload schema and content type.
- Parent message or causal reference.
- Artifact references and provenance.
- Trace context and idempotency key.

Require only fields that have operational value.

### 3. Define message types

Use a small explicit vocabulary such as capability announcement, task request, task accepted, progress, artifact produced, input required, completion, rejection, cancellation, failure, acknowledgement, and heartbeat. Define valid sender, receiver, payload, and resulting state for each type.

### 4. Define task lifecycle

Specify allowed states and transitions, including requested, accepted, running, waiting-for-input, completed, failed, cancelled, and expired. Reject illegal transitions deterministically. Deduplicate repeated messages by message or idempotency key and return the prior acknowledgement or result without repeating side effects.

### 5. Define delivery semantics

Choose at-most-once, at-least-once, or effectively-once behavior per message type. Define acknowledgement, timeout, retry owner, deduplication, ordering, replay, and cancellation behavior. Any effectively-once claim must identify the deduplication store, persistence boundary, idempotent operation, and failure assumptions that make the claim true.

### 6. Define artifact exchange

Prefer references for large artifacts. Specify format, schema version, owner, immutability, checksum, access policy, retention, and whether downstream agents may modify or only derive from the artifact.

### 7. Define ambiguity and negotiation

Specify how agents request missing input, reject unsupported tasks, advertise capabilities, negotiate versions, and decline work outside authority. Do not silently reinterpret an incompatible request.

### 8. Define security and privacy

Authenticate participants, authorize each action, validate payloads, limit message and artifact size, prevent confused-deputy delegation, redact secrets, and preserve tenant boundaries.

### 9. Define compatibility

Document additive and breaking changes, unknown-field handling, version negotiation, deprecation, and rollout order. Consumers must not depend on undocumented prose.

### 10. Test the protocol

Cover normal handoff, duplicate request, delayed acknowledgement, out-of-order progress, unsupported capability, malformed payload, expired task, cancellation race, unauthorized sender, and version mismatch.

## Required Output

Produce:

1. Participant and capability table.
2. Common envelope schema.
3. Message catalogue with payload schemas.
4. Task-state machine and sequence diagrams.
5. Delivery, retry, ordering, and cancellation rules.
6. Artifact contract and provenance rules.
7. Security and authorization assumptions.
8. Versioning and compatibility policy.
9. Conformance test checklist.

## Quality Gates

- Every message type has one semantic purpose.
- Every request reaches acknowledgement, rejection, expiry, cancellation, completion, or failure.
- Duplicate and out-of-order messages have defined behavior.
- Large artifacts are not copied through chat messages unnecessarily.
- Delegated authority is explicit and bounded.
- Protocol evolution does not rely on all participants upgrading simultaneously.

## Runtime Boundary

This skill defines the data-plane contract. Actual delivery, discovery, identity, authentication, persistence, streaming, and A2A transport require agents, servers, plugins, or application infrastructure.
