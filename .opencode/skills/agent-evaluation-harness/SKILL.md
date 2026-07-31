---
name: agent-evaluation-harness
description: "Agent evaluation, LLM regression testing, trajectory assessment, judge rubrics, quality metrics, latency, token cost, drift, and release gates. Use when proving that an agent behaves correctly or measuring an agent change against a baseline."
---

# Agent Evaluation Harness

Convert desired agent behavior into repeatable evidence. Evaluate final answers, intermediate trajectories, tool behavior, safety boundaries, and operational cost.

## Use This Skill When

- An agent or prompt is being introduced or changed.
- A failure must become a regression case.
- The team needs a quality baseline or release gate.
- Accuracy alone hides routing, tool, latency, or cost defects.
- An improvement loop needs evidence before promotion.

This skill is agent-specific. Use ordinary unit-test guidance for deterministic application logic that does not involve agent behavior.

## Required Inputs

- Agent purpose, users, and risk level.
- Behavioral requirements and forbidden behavior.
- Available traces, fixtures, tools, and reference answers.
- Current baseline and proposed change when comparing versions.
- Quality, latency, token, and cost constraints.

## Evidence States

Declare one state before reporting results:

- **PLANNED:** fixtures, thresholds, and execution procedure are designed but no run was attempted.
- **NOT RUN:** execution was intended but unavailable, blocked, or declined; record the exact reason.
- **EXECUTED:** fixtures ran through the named runner and observed outputs were captured.

Label every value as **PROPOSED**, **SUPPLIED**, or **OBSERVED**. Never present proposed thresholds, supplied historical numbers, or estimates as measurements from this evaluation.

## Workflow

### 1. Write the behavioral contract

Define what the agent must do, may do, must not do, and when it must ask, refuse, escalate, or stop. Make each requirement observable.

### 2. Build the evaluation matrix

Include representative slices:

- Typical happy paths.
- Boundary and ambiguous requests.
- Invalid or adversarial inputs.
- Tool and dependency failures.
- Long-context and stale-context cases.
- Permission and escalation cases.
- Cost or latency stress cases.

Prioritize consequential behavior over raw case count.

### 3. Select the strongest evaluator per property

Prefer, in order:

1. Deterministic assertions.
2. Schema and invariant checks.
3. Reference or property-based comparison.
4. Trajectory checks.
5. Human rubric.
6. LLM-as-judge with calibration examples.

Do not use an LLM judge for a property that code can verify exactly.

### 4. Evaluate trajectories

Check route choice, tool selection and arguments, evidence use, forbidden calls, retry count, ordering constraints, approval gates, and termination. Avoid requiring one exact trajectory when several are valid; assert invariants instead.

### 5. Define metrics and thresholds

Specify pass rate by slice, critical-case policy, latency percentiles, token and monetary cost, tool-call count, escalation rate, and stability across repeated runs. Averages must not hide critical failures.

### 6. Establish the baseline

Record model, prompts, tools, configuration, dataset version, environment, and repeated-run variance. Compare changes on the same fixture set. If no executed baseline exists, state that explicitly and produce a baseline-collection plan instead of a numeric comparison.

### 7. Run and classify failures

Run only when a suitable runner, dependencies, credentials, and permissions are available. Separate agent defects, evaluator defects, flaky dependencies, data gaps, and expected nondeterminism. Preserve failing inputs and observed traces. If execution is unavailable, remain in PLANNED or NOT RUN state.

### 8. Decide promotion or rollback

Issue a promotion or rollback decision only from EXECUTED evidence. Promote only when critical cases pass, aggregate thresholds hold, no protected slice regresses beyond tolerance, and cost remains inside budget. Otherwise return INSUFFICIENT EVIDENCE with the missing execution needed to decide.

## Required Output

Return:

1. Behavioral contract.
2. Evaluation matrix with risk and evaluator type.
3. Fixture or dataset specification.
4. Metric definitions and thresholds.
5. Evidence state and provenance label for every reported value.
6. Baseline and candidate scorecard only when supported by EXECUTED evidence; otherwise a collection plan.
7. Failure taxonomy with reproducible evidence when observed.
8. PASS, PASS WITH RISKS, or BLOCK only for EXECUTED evaluations; otherwise INSUFFICIENT EVIDENCE.
9. Promotion, remediation, rollback, or next-execution recommendation.

## Judge Rules

- Blind the judge to version identity.
- Give a criterion-specific rubric and counterexamples.
- Require evidence for each score.
- Calibrate against human-reviewed examples.
- Use repeated judging or multiple judges only when variance justifies the cost.
- Treat judge output as a measurement, not ground truth.

## Quality Gates

- Every contract requirement maps to at least one case.
- High-risk behavior has deterministic checks where possible.
- Evaluation includes failure and refusal behavior.
- Results are reproducible enough to compare versions.
- Critical regressions cannot be averaged away.
- The report separates observed facts from evaluator interpretation.
- No verdict or numeric score implies execution that did not occur.

## Runtime Boundary

This skill can author fixtures and may run them only when a suitable runner, dependencies, credentials, and permissions are available. Continuous trace capture, production monitoring, automatic judging, and deployment promotion require telemetry, CI, or application integration. Never claim a fixture was executed unless observed output was captured this turn.
