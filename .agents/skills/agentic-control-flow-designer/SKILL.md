---
name: agentic-control-flow-designer
description: "Agent workflow, state machine, prompt chain, routing, parallel fan-out/fan-in, reflection loop, tool stage, and termination design. Use ONLY when the primary deliverable is the temporal stages, routes, joins, and termination rules of an agent execution flow."
---

# Agentic Control-Flow Designer

Turn a goal into a bounded execution graph with explicit state, transitions, joins, recovery paths, and terminal conditions.

## Scope

Use this skill for temporal execution design: what runs, in what order, under which conditions, and when execution stops. Use `multi-agent-topology-designer` when the main question is participants and authority, `inter-agent-protocol-designer` for message contracts, `agent-recovery-state-machine` for recovery policies, and `resource-aware-dispatch-designer` for resource allocation.

## Required Inputs

- Goal, deliverable, and observable acceptance criteria.
- Available tools, agents, data, and side effects.
- Known dependencies and irreversible operations.
- Latency, cost, retry, and iteration budgets.
- Error, ambiguity, and approval policies.

## Workflow

### 1. Define the execution contract

State the initial inputs, final artifact, invariants, excluded scope, and exact terminal conditions. Replace subjective completion language with observable checks.

### 2. Identify stages and state

Decompose the work into stages that each have one purpose. For every stage define input state, operation, output state, validation, and possible failure classes.

### 3. Choose control-flow primitives

- Use a chain when each stage depends on the previous output.
- Use a route when input class or state determines the next stage.
- Use fan-out only for independent work.
- Use fan-in only with an explicit aggregation schema.
- Use reflection only when a rubric can detect a correctable defect.
- Use a tool stage when external state or deterministic computation is required.
- Use an approval gate before consequential or irreversible actions.

### 4. Specify routes

For each branch define a predicate, confidence threshold, default branch, ambiguity behavior, and terminal behavior. Branches must be exhaustive or have a safe unknown path.

### 5. Specify parallelism and joins

Record independence assumptions, shared-state restrictions, maximum fan-out, completion policy, partial-failure behavior, and merge ownership. Do not parallelize tasks that write the same artifact without serialization.

### 6. Bound iterative loops

Every plan, search, reflection, or repair loop needs a progress signal, maximum rounds, budget, no-progress condition, and fallback. Stop when the acceptance condition is met, not when the model feels satisfied.

### 7. Add failure and recovery transitions

Classify errors as retryable, repairable, degradable, escalation-required, or terminal. Route each class to one explicit recovery action and define where execution resumes.

### 8. Add observability

Identify state transitions, route decisions, tool calls, validation results, retries, and budget consumption that must be recorded to diagnose execution.

### 9. Simulate the graph

Trace at least:

- Happy path.
- Ambiguous route.
- Partial parallel failure.
- Invalid tool result.
- Exhausted iteration budget.
- Human rejection or timeout when applicable.

## Required Output

Produce:

```markdown
## Execution Contract
- Goal:
- Initial inputs:
- Final artifact:
- Invariants:
- Terminal conditions:

## State and Stage Table
| Stage | Input | Action | Output | Validation | Failure route |

## Route and Join Rules
| Source | Predicate/event | Destination | Default/timeout behavior |

## Budgets
- Maximum steps:
- Maximum parallelism:
- Maximum retries:
- Maximum reflection/search rounds:

## Scenario Traces
```

Include a Mermaid state or flow diagram when the workflow has more than three stages.

## Quality Gates

- No stage has multiple unrelated purposes.
- Routes are exhaustive or include an unknown path.
- Parallel branches are independent.
- Joins define partial-failure behavior.
- Loops have progress tests and hard limits.
- Side effects occur only after validation and required approval.
- Every execution reaches success, safe degradation, escalation, or explicit failure.

## Runtime Boundary

The workflow may be followed in-session only as best-effort, non-durable instruction following. Transitions, joins, atomic gates, recovery, and side effects remain conditional on available tools and permissions. Durable state machines, queues, retries, scheduling, and enforcement must be implemented in an orchestrator, plugin, or application runtime.
