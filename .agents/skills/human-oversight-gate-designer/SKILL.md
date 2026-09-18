---
name: human-oversight-gate-designer
description: "Human-in-the-loop, approval gate, escalation policy, reviewer evidence, pause/resume, timeout default, rollback, and audit design. Use when an agent may make irreversible, costly, privileged, regulated, or materially ambiguous decisions."
---

# Human Oversight Gate Designer

Place human judgment where it changes risk, not as a blanket interruption. Give reviewers enough evidence and clear options to make an accountable decision.

## Required Inputs

- Workflow, actions, and decision points.
- Assets, users, and potential impact.
- Reversibility, uncertainty, cost, privilege, and regulatory constraints.
- Reviewer roles, availability, and response-time expectations.
- State persistence, audit, and rollback capabilities.

## Workflow

### 1. Inventory consequential decisions

List actions that mutate external state, spend meaningful resources, disclose sensitive data, change permissions, publish externally, cross legal or policy boundaries, or rely on unresolved ambiguity.

### 2. Score the need for oversight

Before assigning a tier, define domain-specific scales and threshold rules for impact, reversibility, uncertainty, novelty, privilege, data sensitivity, and time pressure. Record the factor values, assignment rule, and policy source for every decision. Do not collapse the factors into an unexplained score.

Apply these hard overrides:

- Policy- or law-prohibited actions remain **Prohibited** regardless of score or approval.
- Actions subject to mandated separation of duties remain **Dual control**.
- Missing material evidence cannot default to **Automatic**.
- High-impact irreversible actions require **Review** or **Dual control** even when model confidence is high.

Then use the project's documented thresholds to assign one risk tier:

- **Automatic:** low impact, reversible, validated.
- **Notify:** action proceeds but creates a visible record.
- **Review:** human confirmation is required before commitment.
- **Dual control:** two independent approvals are required.
- **Prohibited:** no approval can make the action acceptable.

When no domain policy exists, propose conservative thresholds, label them PROPOSED, and require human adoption before treating them as authoritative.

### 3. Place the gate

Gate immediately before the consequential commit, after enough analysis exists to support a decision. Avoid asking approval before the concrete payload, diff, transaction, or action is visible.

### 4. Build the reviewer packet

Include:

- Decision requested and deadline.
- Proposed action and exact scope.
- Evidence and provenance.
- Confidence and unresolved uncertainty.
- Expected benefit and worst credible harm.
- Cost and affected systems or users.
- Alternatives, including doing nothing.
- Rollback or compensation plan.

### 5. Define reviewer choices

Use explicit outcomes: approve, reject, request changes, narrow scope, defer, or escalate. Define resulting state for each choice. Free-form comments may supplement but must not replace the decision.

### 6. Define timeout and unavailability

Choose fail closed, safe fallback, defer, or escalate. Never interpret silence as approval for a consequential action unless the policy explicitly and safely permits it.

### 7. Define pause and resume

Persist validated state, pending action, artifact versions, approval identity, expiry, and resume preconditions. Revalidate stale data or changed artifacts before execution.

### 8. Define identity and audit

Specify who may approve, separation of duties, authentication strength, delegation, decision reason, timestamp, artifact hash, and retention.

### 9. Test the gate

Exercise approval, rejection, requested changes, timeout, reviewer unavailable, stale approval, changed artifact, unauthorized approver, and rollback after approval.

## Required Output

Return:

1. Decision and risk inventory.
2. Factor scales, thresholds, hard overrides, and policy sources.
3. Recorded factor values and assignment rule for each tier decision.
4. Gate placement diagram or state machine.
5. Escalation and reviewer-role matrix.
6. Reviewer packet template.
7. Allowed decisions and state transitions.
8. Timeout, pause/resume, and stale-approval rules.
9. Identity and audit requirements.
10. Scenario test checklist.

## Quality Gates

- Every gate protects a named risk.
- Every tier assignment is reproducible from recorded rules and evidence.
- Review occurs before commitment and after evidence is available.
- Reviewers see exact scope, consequences, and alternatives.
- Approval expires when relevant state changes.
- Rejection and timeout lead to safe states.
- The design minimizes approval fatigue.
- Prohibited actions cannot be approved through the ordinary gate.

## Runtime Boundary

Conversation-level confirmation is not a durable approval system. Guaranteed blocking, reviewer identity, dual control, audit retention, and resumable state require application or plugin support.
