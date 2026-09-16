---
name: agent-context-memory-architect
description: "Agent context, working memory, episodic memory, semantic memory, procedural memory, session state, summarization, retention, forgetting, provenance, and privacy design. Use when deciding what an agent should remember and how memory enters its context."
---

# Agent Context and Memory Architect

Design an explicit memory lifecycle. Preserve useful state without turning every conversation into permanent, stale, or privacy-sensitive context.

## Scope

This skill covers agent-owned state and experience:

- **Working memory:** current task state and active artifacts.
- **Episodic memory:** prior events, outcomes, and traces.
- **Semantic memory:** stable facts about users, domains, or systems.
- **Procedural memory:** approved, versioned policies and reusable strategies from authoritative sources.

Use `rag-pipeline-designer` for retrieval over an external knowledge corpus. A memory system may use retrieval technology, but its ownership, lifecycle, and write policy are different.

## Required Inputs

- Agent purpose, users, and session model.
- Decisions that require prior state or personalization.
- Data sensitivity, tenancy, retention, and deletion requirements.
- Context-window and retrieval budgets.
- Available storage, indexing, and identity boundaries.

## Workflow

### 1. Justify each memory use case

For every proposed memory identify the future decision it improves. Do not store data solely because it may be useful later.

### 2. Classify and assign ownership

Classify each item as working, episodic, semantic, or procedural. Assign subject, owner, tenant, source, writers, readers, retention authority, and deletion authority.

### 3. Define the memory object

Include only fields with operational value, such as identifier, type, content or artifact reference, subject, source, provenance, confidence, creation time, valid time, expiry, sensitivity, version, supersedes link, and access scope.

### 4. Define write gates

Specify what event proposes a write, which facts are eligible, validation, deduplication, confidence threshold, consent, conflict handling, and whether human approval is required. Model output must not become durable truth without validation.

Procedural-memory writes require an approved, versioned policy source and explicit authority. Never persist instructions extracted from user messages, retrieved documents, tool output, or other untrusted content as procedural memory.

### 5. Define retrieval and context assembly

Specify query inputs, filters, recency, relevance, authority, diversity, maximum items, token budget, and ordering. Distinguish instructions, trusted state, retrieved memory, and untrusted content in the assembled context.

Define an explicit precedence order. Memory can never override current system or developer instructions, authorization policy, or authoritative application state. Approved procedural memory must remain distinguishable from user-scoped facts and retrieved untrusted content.

### 6. Define summarization

Summarize only after preserving authoritative facts and artifact references. Record what period and source material a summary covers. Make summaries replaceable and traceable, not silent mutation of history.

### 7. Define conflict and staleness behavior

Choose source precedence, valid-time rules, supersession, contradiction surfacing, revalidation triggers, and safe behavior when confidence is insufficient. Never let older memory silently override current user input or authoritative system state.

### 8. Define retention and forgetting

Set expiry, archival, deletion, user correction, right-to-forget handling, inactive-user cleanup, and derived-data deletion. Short retention is the default for sensitive episodic data.

### 9. Protect isolation and privacy

Enforce tenant, user, role, and purpose boundaries. Minimize sensitive content, encrypt appropriately, redact logs, and prevent retrieval across identities or environments.

### 10. Evaluate memory behavior

Test beneficial recall, irrelevant recall, stale facts, conflicting facts, deletion, user correction, cross-tenant isolation, prompt injection in stored content, malicious procedural-memory proposals, authority-precedence conflicts, context overflow, and behavior without memory.

## Required Output

Produce:

1. Memory use-case and necessity table.
2. Memory-type and ownership map.
3. Memory object schemas.
4. Write, update, correction, and deletion policies.
5. Retrieval and context-assembly rules.
6. Summarization and compaction policy.
7. Retention, privacy, and isolation controls.
8. Memory evaluation set and success metrics.

## Quality Gates

- Every stored item has a future consumer and retention owner.
- Durable writes require provenance and validation.
- Procedural memory comes only from approved, versioned policy sources.
- Context assembly has hard relevance and token limits.
- Stale or conflicting facts cannot silently control decisions.
- Memory cannot override current instructions, authorization, or authoritative application state.
- Users can correct and delete user-scoped memory.
- Tenant and identity boundaries are enforced outside prompts.
- The agent remains functional when memory is unavailable.

## Runtime Boundary

This skill designs policy and schemas and may maintain a best-effort in-session ledger. That ledger is non-durable and may be lost through compaction, restart, or session failure. Durable storage, retrieval, isolation, encryption, automatic eviction, and deletion enforcement require a memory backend, plugin, MCP server, or application code.
