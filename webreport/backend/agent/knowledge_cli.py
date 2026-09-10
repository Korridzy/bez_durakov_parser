"""Validate the configured operator knowledge folder before deployment."""

import sys

from bd_shared.config import (
    DATABASE_NAME,
    KNOWLEDGE_DIR,
    KNOWLEDGE_MAX_DOC_BYTES,
    KNOWLEDGE_MAX_PERSONA_CHARS,
    KNOWLEDGE_MAX_SUMMARY_CHARS,
    KNOWLEDGE_MAX_TITLE_CHARS,
    KNOWLEDGE_MAX_TOPICS,
)

from agent.knowledge import KnowledgeError, KnowledgeLimits, load_knowledge, validate_limits


def main() -> int:
    """Validate knowledge using the same config and loader as backend startup."""
    knowledge_limits = KnowledgeLimits(
        max_title_chars=KNOWLEDGE_MAX_TITLE_CHARS,
        max_summary_chars=KNOWLEDGE_MAX_SUMMARY_CHARS,
        max_persona_chars=KNOWLEDGE_MAX_PERSONA_CHARS,
        max_topics=KNOWLEDGE_MAX_TOPICS,
        max_doc_bytes=KNOWLEDGE_MAX_DOC_BYTES,
        max_bytes_per_turn=131072,
    )

    try:
        validate_limits(knowledge_limits)
        if KNOWLEDGE_DIR is None:
            print(
                "Knowledge folder is not configured (webreport.knowledge_dir is unset); "
                "the agent runs without dataset knowledge."
            )
            return 0
        if not KNOWLEDGE_DIR.exists():
            print(
                f"Knowledge folder not found at {KNOWLEDGE_DIR.resolve()}; "
                "the agent runs without dataset knowledge."
            )
            return 0

        loaded = load_knowledge(KNOWLEDGE_DIR, DATABASE_NAME, knowledge_limits)
    except KnowledgeError as error:
        print(f"Knowledge folder is invalid: {error}", file=sys.stderr)
        return 1

    print(f"Knowledge folder is valid: {KNOWLEDGE_DIR.resolve()} ({len(loaded.topics)} topics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
