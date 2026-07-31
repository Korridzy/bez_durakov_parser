---
name: resource-aware-dispatch-designer
description: "Model routing, tool selection, agent dispatch, token budget, cost budget, latency SLO, concurrency, context pruning, caching, prioritization, and graceful degradation. Use ONLY when the primary deliverable is model, tool, agent, or context allocation under quality, cost, and latency constraints."
---

# Resource-Aware Dispatch Designer

Create an explicit policy for spending models, tools, context, time, and parallelism according to task value and risk.

## Required Inputs

- Quality requirements and protected failure cases.
- Latency SLOs and deadlines.
- Token, monetary, rate-limit, and concurrency budgets.
- Available models, tools, agents, and their measured characteristics.
- Workload classes, priorities, and arrival patterns.
- Fallback and degradation constraints.

Use measured data when available. Mark estimates and assumptions when it is not.

## Evidence Mode

Choose one mode:

- **DESIGN ONLY:** no representative execution data is available. Produce a conservative provisional policy and an experiment plan, not claimed performance deltas.
- **MEASURED EVALUATION:** representative workloads were executed and observed measurements are available.

Label every datum **MEASURED**, **SUPPLIED**, or **ESTIMATED**. Never mix these categories in an unlabeled baseline or comparison.

Use `multi-agent-topology-designer` for team structure, `agentic-control-flow-designer` for temporal routing and joins, `inter-agent-protocol-designer` for message contracts, and `agent-recovery-state-machine` for failure recovery.

## Workflow

### 1. Define optimization objectives

State the primary objective and hard constraints. Examples: minimize cost while maintaining a quality floor, minimize latency for interactive requests, or maximize verified quality inside a fixed budget.

### 2. Establish a baseline

Measure or estimate quality by workload slice, latency percentiles, input and output tokens, model and tool cost, tool-call count, retry rate, concurrency, cache hit rate, and failure rate.

### 3. Classify work

Create a small taxonomy using complexity, uncertainty, impact, reversibility, context size, tool need, and urgency. Define deterministic signals where possible and a safe unknown class.

### 4. Define dispatch tiers

For each class select initial model, optional specialist agent, allowed tools, context budget, reasoning or search budget, timeout, and escalation tier. Cheap-first routing must include confidence and risk gates.

### 5. Optimize context and retrieval

Remove duplicate or low-value context, summarize with provenance, retrieve on demand, cap result count, cache stable artifacts, and avoid sending private or irrelevant state to stronger external models.

### 6. Set parallelism policy

Parallelize independent latency-bound work only when fan-out cost and rate limits are acceptable. Define maximum width, queue priority, cancellation, speculative-work policy, and fan-in deadline.

### 7. Set escalation and fallback

Escalate when confidence, quality checks, or risk require it. Define stronger-model retry, alternate tool, cached answer, partial response, human review, and safe unavailability in order.

### 8. Define budgets and stop conditions

Set per-request and aggregate limits for tokens, cost, time, tool calls, agents, retries, and exploration rounds. Stop or degrade before overrunning silently.

### 9. Validate tradeoffs

In MEASURED EVALUATION mode, run representative workload slices against the baseline and report quality, latency, and cost deltas separately. In DESIGN ONLY mode, define the workload, instrumentation, thresholds, sample size, and comparison procedure needed to measure those deltas. Reject savings that regress critical cases or transfer unacceptable load elsewhere.

### 10. Define feedback and drift review

Specify monitored metrics, alert thresholds, route-distribution drift, model/provider changes, budget review cadence, and rollback criteria.

## Required Output

```markdown
## Objectives and Hard Constraints

## Evidence Mode and Data Provenance

## Workload Classes
| Class | Signals | Risk | Quality floor | Priority |

## Dispatch Matrix
| Class | Model/agent | Tools | Context budget | Time/cost budget | Escalation |

## Concurrency and Queue Policy

## Cache and Context Policy

## Fallback/Degradation Ladder

## Baseline Comparison

Use an experiment plan instead when mode is DESIGN ONLY.

## Monitoring and Rollback
```

## Quality Gates

- Quality floors are defined before cost optimization.
- High-impact cases cannot route solely on apparent simplicity.
- Unknown or low-confidence classification has safe behavior.
- Every escalation and fallback has a budget.
- Parallelism accounts for cancellation and wasted speculative work.
- Results report quality, latency, and cost without collapsing them into one opaque score.
- Every number is labeled MEASURED, SUPPLIED, or ESTIMATED.
- DESIGN ONLY output does not claim observed improvements.
- Runtime policy can be rolled back when workload or provider behavior changes.

## Runtime Boundary

This skill designs and evaluates dispatch policy. Live metering, model switching, queues, quotas, caching, and concurrency enforcement require provider telemetry and runtime hooks.
