---
name: agent-recovery-state-machine
description: "Agent resilience, exception recovery, retry, timeout, fallback, checkpoint, compensation, circuit breaker, graceful degradation, and escalation design. Use ONLY when the primary deliverable is a recovery policy for model, tool, network, state, or orchestration failures."
---

# Agent Recovery State Machine

Design recovery before failure occurs. Map each failure class to one bounded response and a known resume or terminal state.

Use `agentic-control-flow-designer` for the normal temporal workflow, `inter-agent-protocol-designer` for message delivery semantics, and `resource-aware-dispatch-designer` for model/tool allocation under resource constraints.

## Use This Skill When

- Tool, model, network, or dependency calls can fail.
- A workflow performs multi-step or irreversible operations.
- Retries produce duplication, cost spikes, or inconsistent state.
- The system needs checkpoints, fallbacks, compensation, or degraded service.
- Generic debugging has identified a failure that now needs a durable recovery policy.

## Required Inputs

- Workflow stages and state transitions.
- External dependencies and side effects.
- Idempotency, transaction, and rollback capabilities.
- Availability, latency, cost, and correctness objectives.
- Escalation contacts and human-approval requirements.

## Workflow

### 1. Inventory failures by stage

For every stage identify invalid input, model refusal or malformed output, tool-selection error, tool execution error, timeout, rate limit, dependency outage, permission denial, stale state, partial write, inconsistent artifact, budget exhaustion, cancellation, and unknown failure.

### 2. Classify each failure on independent dimensions

Record every dimension rather than forcing one mixed class:

- **Retryability:** correctable, transient, persistent, or unknown.
- **Side-effect state:** none, partial, committed, or unknown.
- **Compensation:** available, unavailable, unnecessary, or unknown.
- **Degradation:** eligible, ineligible, or unknown.
- **Final disposition:** resume, degrade, escalate, or terminate.

Then select one primary response and list its preconditions. A failure may be persistent, partially committed, compensatable, and escalation-required at the same time.

### 3. Define retry policy

Retry only transient failures. Set maximum attempts, backoff, jitter, overall deadline, retryable codes, idempotency requirement, and budget. Never retry authorization denial, invalid input, or deterministic rejection unchanged.

### 4. Define checkpoints

Checkpoint only validated state. Record workflow version, completed stages, artifact references, side-effect receipts, pending work, and resume preconditions. Define checkpoint retention and invalidation.

### 5. Define compensation

For every side effect specify atomicity, commit point, idempotency key, compensation action, compensation owner, and behavior when compensation itself fails.

### 6. Define fallback and degradation

Order fallbacks from closest semantic equivalent to safe unavailability. State the quality loss, data freshness, permissions, user disclosure, and exit condition for each degraded mode.

### 7. Define circuit breaking

For unstable dependencies define failure threshold, open duration, probe behavior, half-open success criteria, queue or rejection behavior, and operator visibility.

### 8. Define escalation and terminal behavior

Package current state, attempted recovery, evidence, remaining options, risk, and recommended action. Preserve enough state to resume without repeating committed side effects.

### 9. Test recovery paths

Inject one representative failure for every policy class. Verify retry bounds, no duplicate side effects, checkpoint resume, fallback disclosure, cancellation, compensation, escalation payload, and safe terminal state.

## Required Output

```markdown
## Recovery Objectives

## Failure-Response Matrix
| Stage | Failure signal | Retryability | Side-effect state | Compensation | Degradation | Primary response | Preconditions/limit | Final disposition |

## Retry and Deadline Policy

## Checkpoint Schema and Resume Rules

## Compensation Map

## Fallback Ladder

## Circuit-Breaker Rules

## Escalation Packet

## Failure-Injection Tests
```

## Quality Gates

- Every known failure reaches one response and one next state.
- Orthogonal failure properties are recorded separately.
- Retry policies are code- and condition-specific.
- Mutating retries are idempotent or safely deduplicated.
- Checkpoints contain only validated state.
- Degraded output is labeled and remains safe.
- Recovery cannot loop indefinitely or exceed the original task budget silently.
- Unknown failures fail safely and retain diagnostic evidence.

## Runtime Boundary

This skill creates the recovery model and test plan. Automatic retries, durable checkpoints, circuit breakers, compensation, and failover must be implemented and observed in the workflow runtime.
