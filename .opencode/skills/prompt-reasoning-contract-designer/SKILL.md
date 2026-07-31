---
name: prompt-reasoning-contract-designer
description: "Prompt contract, agent node instructions, structured output, decomposition, ReAct, comparison, verification, reflection, exploration, examples, repair, and stopping criteria. Use when specifying or repairing one reasoning node inside an agent workflow."
---

# Prompt and Reasoning Contract Designer

Specify observable behavior for one model-powered node. Optimize the contract for reliable inputs, outputs, evidence, validation, repair, and termination rather than requesting hidden chain-of-thought.

## Scope

Use this skill for an individual prompt, agent role, or workflow node. Use `agentic-control-flow-designer` for the graph around the node and `agent-evaluation-harness` for system-level evaluation.

## Required Inputs

- Node purpose and downstream consumer.
- Input fields, source trust, and context limits.
- Output schema and acceptance criteria.
- Available tools and side-effect restrictions.
- Representative success, boundary, and failure examples.
- Latency, token, and iteration budget.

## Workflow

### 1. Define the node contract

State one responsibility, required inputs, produced output, invariants, forbidden behavior, uncertainty behavior, and terminal conditions. Split nodes with unrelated responsibilities.

### 2. Select the simplest reasoning strategy

| Strategy | Use when |
|---|---|
| Direct transformation | Inputs fully determine a short output |
| Decomposition | Several dependent subproblems must be solved |
| Classification/routing | A closed set of branches exists |
| Compare-and-select | Candidate options have an explicit rubric |
| Evidence verification | Claims must be checked against sources or tools |
| ReAct-style tool loop | Information or action must be obtained dynamically |
| Program-aided reasoning | Deterministic code can calculate or validate the answer |
| Bounded reflection | A rubric can detect and repair a draft defect |
| Bounded exploration | Multiple hypotheses are warranted and can be pruned |

Do not request verbose private reasoning. Ask for concise rationale, evidence, calculations, assumptions, or structured intermediate artifacts only when they are needed for validation or downstream work.

### 3. Structure instructions

Write role and objective, trusted inputs, untrusted data boundaries, ordered procedure, tool rules, output schema, validation, uncertainty behavior, and stop conditions. Put authoritative constraints before task data.

### 4. Define structured output

Use a schema that rejects missing, contradictory, or out-of-range fields. Distinguish result data, evidence, confidence, warnings, and error status. Avoid prose when a downstream program consumes the output.

### 5. Define tool behavior

Specify when each tool is required, optional, or prohibited; argument constraints; result validation; maximum calls; and what to do on timeout, malformed output, or permission denial.

### 6. Add examples strategically

Include the minimum examples needed to distinguish valid behavior, edge cases, refusal or abstention, and common confusion. Examples must obey the current schema and not introduce contradictory rules.

### 7. Add validation and repair

Validate schema, invariants, evidence coverage, and tool results. Permit one bounded repair path for correctable output. Escalate or fail after the repair budget rather than looping.

### 8. Define uncertainty and stopping

Specify when to answer, retrieve, ask one material question, abstain, refuse, or escalate. Exploration and reflection require progress signals and hard limits.

### 9. Derive evaluation fixtures

Create happy, boundary, ambiguous, malformed-input, tool-failure, adversarial-content, and budget-exhaustion cases. Assert observable outputs and invariants, not hidden reasoning text.

## Required Output

```markdown
## Node Contract
- Responsibility:
- Inputs:
- Output:
- Invariants:
- Forbidden behavior:
- Uncertainty behavior:
- Stop conditions:

## Selected Reasoning Strategy

## Prompt

## Output Schema

## Tool Policy

## Examples

## Validation and Repair

## Evaluation Fixtures
```

## Quality Gates

- The node has one clear responsibility.
- Inputs and instructions are explicitly separated.
- Outputs are machine-checkable where appropriate.
- Tools are bounded and results are validated.
- Reflection or exploration cannot run unbounded.
- Uncertainty produces clarification, abstention, or escalation instead of fabrication.
- Evaluation checks visible behavior without requiring private chain-of-thought.

## Runtime Boundary

This skill produces the behavioral contract and fixtures. Structured-output enforcement, tool permissions, secret isolation, and retry limits must also be implemented in the runtime.
