---
name: multi-agent-topology-designer
description: "Multi-agent topology, agent team architecture, supervisor-worker, router-specialist, peer, debate, hierarchy, and fan-out/fan-in design. Use ONLY when the primary deliverable is the participants, roles, authority, and communication-edge topology of an agent team."
---

# Multi-Agent Topology Designer

Design the organization of an agent team before defining prompts or launching workers. Optimize for clear ownership, minimal coordination, observable convergence, and bounded cost.

Use `agentic-control-flow-designer` for temporal stages and joins, `inter-agent-protocol-designer` for message envelopes and delivery semantics, `agent-recovery-state-machine` for retries and compensation, and `resource-aware-dispatch-designer` for model/tool/context allocation.

## Use This Skill When

- A task may benefit from several specialized agents.
- The user asks for a supervisor, router, debate, hierarchy, swarm, or parallel team.
- Existing agents duplicate work, conflict, or fail to integrate results.
- You need an architecture for agent ownership, authority, and communication edges.

Do not introduce multiple agents merely because parallel execution is available. Prefer one agent when the work is tightly coupled, small, or dominated by shared context.

## Required Inputs

Collect or infer:

- Goal and acceptance criteria.
- Work units and dependency relationships.
- Required specialties and trust boundaries.
- Latency, token, cost, and concurrency limits.
- Decisions requiring a single accountable owner.
- Failure isolation and human-escalation requirements.

Ask a question only when a missing constraint would change the selected topology.

## Workflow

### 1. Prove that a team is warranted

Compare a single-agent baseline with a team. Multi-agent execution is justified when at least one condition holds:

- Independent work can run concurrently.
- Distinct expertise materially improves quality.
- Independent critique reduces a consequential error risk.
- Isolation protects secrets, permissions, or failure domains.
- The workload exceeds one agent's practical context boundary.

### 2. Build the dependency graph

List work units, required inputs, produced artifacts, and dependencies. Mark each edge as sequential, parallel, conditional, iterative, or approval-gated.

### 3. Select the smallest suitable topology

| Topology | Prefer when | Avoid when |
|---|---|---|
| Sequential handoff | Each stage transforms a stable artifact | Rework frequently invalidates earlier stages |
| Fan-out/fan-in | Probes are independent and results can be merged | Workers mutate shared state |
| Router-specialist | Requests fall into distinct capability classes | Classification confidence is poor |
| Supervisor-worker | One role must own decomposition and integration | Supervisor becomes a context bottleneck |
| Hierarchy | Many workers need bounded local coordination | The team is small or latency-sensitive |
| Producer-critic | Quality criteria are explicit and revision is bounded | Critique cannot be objectively resolved |
| Debate/consensus | Independent perspectives reduce high-impact bias | A factual verifier can decide more cheaply |
| Peer/shared artifact | Roles collaborate around a canonical artifact | Concurrent writes cannot be serialized |

Use a hybrid only when no single topology satisfies the dependency graph.

### 4. Define roles and authority

For every agent specify mission, owned decisions, allowed tools, required inputs, output schema, forbidden scope, escalation target, and stop condition. Every decision must have exactly one final owner.

### 5. Define communication edges

For every edge specify sender, receiver, artifact or message, trigger, validation, timeout, retry owner, and whether the exchange is synchronous or asynchronous.

### 6. Define convergence

Choose an explicit merge rule: deterministic aggregation, verifier selection, supervisor synthesis, scored voting, or human decision. Never use vague instructions such as "reach consensus" without a tie-breaker and deadline.

### 7. Bound cost and failure

Set maximum workers, fan-out width, rounds, retries, token or time budget, and degraded single-agent fallback. Identify single points of failure and duplicated context.

### 8. Validate with scenarios

Walk through one happy path, one worker failure, one conflicting-result case, and one budget-exhaustion case. Simplify the topology if ownership or termination is unclear.

## Required Output

Return:

1. Recommendation and single-agent comparison.
2. Mermaid topology diagram.
3. Role and authority matrix.
4. Communication-edge inventory.
5. Convergence and conflict policy.
6. Failure, escalation, and degraded-mode policy.
7. Concurrency and cost envelope.
8. Scenario validation results.

## Quality Gates

- Every role owns a distinct outcome.
- Every edge carries a defined artifact or message.
- Every branch has a join or terminal state.
- Every loop has a budget and stop condition.
- One role owns final integration.
- Removing an agent would measurably harm latency, quality, isolation, or capacity.

## Runtime Boundary

This skill designs the control plane. Actual agent definitions, dispatch, persistence, permissions, and enforcement require OpenCode agents, task tooling, plugins, MCP servers, or application code. Do not claim those capabilities exist until they are verified.
