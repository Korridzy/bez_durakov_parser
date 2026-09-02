---
name: agent-guardrail-designer
description: "Agent guardrails, trust boundaries, prompt-injection defense, input validation, output filtering, tool restrictions, least privilege, refusal, escalation, and adversarial tests. Use when constraining unsafe, unauthorized, or off-policy agent behavior."
---

# Agent Guardrail Designer

Create layered, testable controls around agent inputs, reasoning context, tool access, outputs, and side effects. Treat prompts as guidance, not enforcement.

## Scope

Use this skill to design constructive guardrails for an agent workflow. Use a dedicated security-review skill when the request is to discover exploitable vulnerabilities in an existing implementation.

## Required Inputs

- Agent purpose and allowed user population.
- Data, tools, credentials, and side effects in scope.
- Threat actors, misuse cases, and policy requirements.
- Deployment boundary and existing enforcement mechanisms.
- Acceptable refusal, degradation, and escalation behavior.

## Workflow

### 1. Map assets and trust boundaries

Identify sensitive data, credentials, external systems, privileged tools, untrusted content, model outputs, human reviewers, and every privilege transition.

### 2. Define allowed behavior first

Write narrow capabilities and invariants. For each action classify allowed, conditionally allowed, approval-required, or prohibited. Avoid attempting to enumerate every possible bad string.

### 3. Threat-model the agent path

Cover prompt injection, indirect injection in retrieved content, data exfiltration, confused-deputy behavior, privilege escalation, unauthorized tool use, cross-tenant leakage, unsafe output, denial of wallet or resources, and audit evasion.

### 4. Place layered controls

- **Input boundary:** schema, size, type, encoding, and origin validation.
- **Context boundary:** source labeling, instruction/data separation, provenance, and untrusted-content handling.
- **Planner boundary:** behavioral constraints and approval requirements.
- **Tool boundary:** allowlists, typed schemas, server-side authorization, least privilege, and side-effect limits.
- **Output boundary:** schema validation, sensitive-data checks, policy filtering, and citation requirements.
- **Commit boundary:** approval, transaction limits, dry run, and rollback.

### 5. Choose failure behavior

For every control specify fail closed, fail safe with reduced capability, refuse, ask for clarification, or escalate. Do not allow silent bypass when a validator or policy service is unavailable.

### 6. Constrain resources

Set tool-call, token, time, fan-out, recursion, data-volume, and monetary limits. Define cancellation and cleanup behavior.

### 7. Design refusals and escalation

Refusals should identify the blocked class without leaking bypass details and offer a safe alternative when one exists. Escalation must carry evidence and current state.

### 8. Derive adversarial tests

Test direct and indirect prompt injection, encoded or fragmented instructions, malicious tool arguments, oversized payloads, stale authorization, role confusion, sensitive output, policy-service outage, and cross-session contamination.

### 9. Define monitoring and maintenance

Record policy decisions, denied actions, escalations, anomalous tool patterns, validator failures, and resource-limit events. Define review cadence and ownership for policy changes.

## Required Output

Produce:

1. Asset and trust-boundary map.
2. Allowed/conditional/prohibited policy matrix.
3. Threat and misuse-case inventory.
4. Layered enforcement map with owners.
5. Refusal, degradation, and escalation contract.
6. Resource limits.
7. Adversarial test vectors and expected outcomes.
8. Monitoring and policy-maintenance plan.

## Quality Gates

- Consequential controls are enforced outside natural-language prompts.
- Tool permissions follow least privilege.
- Retrieved content is treated as data, not authority.
- Validator failure has explicit safe behavior.
- Side effects are bounded and auditable.
- Tests target bypasses across multiple layers.
- Human approval does not override prohibited policy.

## Runtime Boundary

This skill defines guardrails but does not create a security boundary. Enforcement belongs in permissions, schemas, sandboxes, tool implementations, policy services, and application code. Verify those controls through real tests.
