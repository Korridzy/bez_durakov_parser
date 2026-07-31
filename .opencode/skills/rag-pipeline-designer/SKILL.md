---
name: rag-pipeline-designer
description: "RAG, retrieval-augmented generation, corpus ingestion, chunking, metadata, hybrid search, reranking, grounding, citations, freshness, access control, prompt-injection defense, and retrieval evaluation. Use when designing or fixing source-grounded agent answers."
---

# RAG Pipeline Designer

Design retrieval that supplies the right evidence, preserves provenance, and makes unsupported claims visible.

## Use This Skill When

- Answers depend on private, changing, or domain-specific sources.
- Users require citations or attributable evidence.
- Existing retrieval returns irrelevant, stale, incomplete, or unauthorized context.
- The problem may need query decomposition or iterative retrieval.

Do not add RAG when the required knowledge is small, stable, and better represented as validated configuration or ordinary application data.

## Required Inputs

- User questions and required answer behavior.
- Corpus sources, formats, owners, and update frequency.
- Access-control, tenancy, privacy, and citation requirements.
- Latency, cost, freshness, and context budgets.
- Existing search, database, graph, or vector infrastructure.

## Workflow

### 1. Define answer and evidence contracts

Specify supported questions, required evidence granularity, acceptable abstention, citation format, freshness, completeness, and how conflicts must be reported.

### 2. Inventory and govern sources

Record authority, owner, format, sensitivity, tenant, valid time, update mechanism, deletion behavior, and trust level. Exclude sources whose provenance or authorization cannot be established.

### 3. Design ingestion

Define parsing, normalization, deduplication, structural preservation, language handling, attachment extraction, checksums, incremental updates, deletion propagation, and ingestion observability.

### 4. Design chunks and metadata

Chunk on semantic or document boundaries rather than fixed size alone. Preserve document, section, heading, source URI or identifier, author, timestamps, permissions, version, and neighboring context. Evaluate overlap instead of assuming it helps.

### 5. Choose indexes and retrieval

Select lexical, vector, relational, graph, or hybrid retrieval according to query type. Define filters, query rewriting, decomposition, top-k, diversity, recency, and authorization before retrieval results reach the model.

### 6. Add reranking and context construction

Rerank against the actual question, remove duplicates, preserve source diversity, fit a hard token budget, and label each passage with provenance and trust. Keep source text separate from instructions.

### 7. Define agentic retrieval only when needed

Use iterative search when one retrieval pass cannot answer multi-hop or ambiguous questions. Bound query count, rounds, tool calls, and no-progress behavior. Require the agent to justify additional retrieval with a missing evidence need.

### 8. Ground generation

Require claims to map to supplied evidence, citations to point to stable source locations, contradictions to be surfaced, and unsupported requests to abstain or ask for more information.

### 9. Protect the pipeline

Apply access filters before ranking, sanitize rendered output, treat retrieved instructions as untrusted data, prevent cross-tenant leakage, constrain URLs and connectors, and propagate deletions.

### 10. Evaluate end to end

Build golden cases covering retrieval relevance and recall, citation correctness, answer support, freshness, abstention, conflicting sources, authorization, injection, latency, and cost. Diagnose retrieval and generation separately.

Every golden case must include corpus version, caller identity and tenant, query, expected relevant passage identifiers or facts, forbidden passages, expected citations or abstention behavior, and slice-specific acceptance thresholds. Mark cases whose oracle still requires human adjudication.

## Required Output

Return:

1. Answer and evidence contract.
2. Source inventory and governance rules.
3. Ingestion and deletion design.
4. Chunk and metadata schema.
5. Retrieval, filtering, reranking, and context policy.
6. Grounding and citation rules.
7. Security and access-control map.
8. Executable golden-case set with corpus version, caller context, expected/forbidden evidence, expected citations or abstention, and metric thresholds.
9. Failure-diagnosis guide for ingestion, retrieval, reranking, and generation.

## Quality Gates

- Every answer class has an evidence requirement.
- Authorization is applied before content reaches the model.
- Citations are stable and traceable to source passages.
- Stale and conflicting sources have explicit behavior.
- Retrieval and generation quality are measured separately.
- Agentic retrieval has strict budgets and stopping conditions.
- The system abstains rather than inventing unsupported claims.

## Runtime Boundary

This skill designs the pipeline and evaluation suite. It does not provide parsers, embeddings, indexes, vector storage, connectors, access enforcement, or query execution; those require implemented infrastructure.
