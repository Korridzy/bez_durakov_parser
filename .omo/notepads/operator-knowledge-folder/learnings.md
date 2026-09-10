# Learnings — operator-knowledge-folder

Conventions, patterns, and successful approaches discovered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

## Poetry lockfile dependency gotcha

Adding a dev dependency to `pyproject.toml` requires running `poetry lock` before `poetry install --no-root`; otherwise Poetry rejects the stale lockfile.

## Ruff inventory patterns

The root scan reports 32 violations across 14 files: `F401` (11), `E402` (10), `F541` (9), and `F841` (2). `E402` is concentrated in `webreport/backend/main.py` (4), `webreport/data_collector/entrypoint.py` (4), `webreport/data_collector/test_entrypoint.py` (1), and `webreport/backend/agents/report_agents.py` (1). `F401` is spread across shared/database and WebReport imports; `F541` spans parser, tests, collector, and setup code; both `F841` findings are in `bd_shared/bd_game.py`.

The targeted `main.py` scan confirms E402 at lines 34-37 after the logger assignment. It does not report the cited `from bd_shared.config import ...` line 20 after `sys.path.insert(0, '/')`, so that first cited site is refuted under the active Ruff behavior. Keep `webreport/backend/main.py` and `webreport/data_collector/entrypoint.py` as the main E402 repair hotspots and preserve the intentional container import-path setup while repairing imports.

## PYTHONPATH roots after Todo 4

- `webreport/backend/main.py`: `webreport/Dockerfile.backend` sets `PYTHONPATH=/` because Compose mounts the package at `/bd_shared`; no narrower parent can resolve that mount.
- `webreport/backend/services/game_data_service.py` and `session_store.py`: the final tracked-source enumeration exposed two more non-test runtime mutations omitted by both fixed counts in the plan. They now share the backend image's `PYTHONPATH=/`; the backend suite and a direct import of both modules passed in that image.
- `webreport/data_collector/fetch_pipeline.py` and `entrypoint.py`: `webreport/Dockerfile.data_collector` also sets `PYTHONPATH=/` because the separate image receives the same `/bd_shared` mount. A live `data_collector` run printed `/` and imported `bd_shared` successfully.
- `webreport/generate_env.py`: host recipes pass the absolute repository root. `webreport/Makefile` derives it with `$(abspath ..)`; root `Makefile` uses `$(CURDIR)` for the generator and its test.
- `webreport/data_collector/test_entrypoint.py`: the root test recipe passes absolute `$(CURDIR)`, and the optimized subprocess imports `webreport.data_collector.entrypoint` through that inherited root instead of mutating `sys.path`.
- `migrations/env.py`: no `PYTHONPATH` was added; Alembic's existing `prepend_sys_path = .` supplies the repository root.

The mandatory literal grep did not print `entrypoint.py` because its sixth mutation was expressed as `__import__("sys").path.insert(0, "/")`; direct file inspection and a broader equivalent-pattern search confirmed and removed it.

After the runtime cleanup, the only tracked `sys.path.insert` sites are E402-clean tests: ten `webreport/backend/test_*.py` modules (`test_agent`, `test_agent_checkpointer`, `test_net_guard`, `test_reasoning`, `test_reasoning_api`, `test_reasoning_filter`, `test_reasoning_partial`, `test_reasoning_seam`, `test_reasoning_span`, `test_top_team_limit`), `webreport/frontend/tests_e2e/conftest.py`, and the function-local isolation in `webreport/test_generate_env.py`. A Ruff E402 scan over all 12 remaining tracked files passed.

## Todo 5 repo-wide Ruff repairs

- `bd_shared/bd_game.py`: fixed F841 by removing two unused `has_conflicts` assignments and the unused `KeyError` alias; fixed F541 by removing an inert f-string prefix.
- `bd_shared/db.py`: fixed two F401 findings by removing unused `os` and `sqlalchemy.func` imports.
- `clear_database.py`: fixed F541 by removing an inert f-string prefix.
- `migrations/versions/a1b2c3d4e5f6_change_team_name_collation_to_binary.py`: fixed F401 by removing the unused SQLAlchemy module alias; `make upgrade-db` still reached the MySQL head.
- `parse_data.py`: fixed F541 by removing an inert f-string prefix.
- `webreport/backend/agents/report_agents.py`: fixed E402 by moving the `report_runtime` import to the import block and fixed F401 with an explicit `ReportAgentSystem` re-export; fallback regex and matching logic remained unchanged, and dedicated route/import-order tests passed.
- `webreport/backend/test_system.py`: fixed three F401 findings by removing unused `os`, `date`, and `datetime` imports; fixed three F541 findings by removing inert f-string prefixes.
- `webreport/data_collector/xlsm_fetch/base_fetcher.py`: fixed F401 by removing the unused `Dict` import.
- `webreport/data_collector/xlsm_fetch/selenium_fetcher.py`: fixed F401 by removing the unused `Dict` import; fixed two F541 findings by removing inert f-string prefixes.
- `webreport/validate_setup.py`: fixed F541 by removing an inert f-string prefix.

The fresh post-Todo-4 scan contained 21 findings across these 10 files. The completed scan is clean, the AC-25 lanes remain green at 75/75/2/59 tests, and the intentional `importlib.import_module` handles in `agent/registry.py` and `agent/tools.py` were not changed.

## Wave 0 complete: lint-gated aggregate suite

- Root `make test` now calls recursive `make lint` before initializing the existing status accumulator or defining `run()`. A lint failure exits immediately, while a clean lint falls through to the previous aggregate recipe unchanged.
- Todo 6 happy-path evidence confirms lint output first, the backend Docker lane reached, AC-25 remained green at 75/75/2/59 tests, data collector passed 12 tests, and frontend passed 24 tests. The final Playwright lane alone failed because `make test-e2e-setup` has not installed Chromium on this machine, which is expected for this todo.
- `bd_shared/config.py` already imports and uses `os`, so appending another `import os` at EOF produces `E402`, not `F401`. The failure-path probe kept that required import and added an adjacent temporary unused `json` import to record the required `F401`; evidence confirms non-zero exit and no Docker command. The scratch edits were fully restored.
- On this host, Wave 6 re-verification may need frontend Poetry dependencies installed, a responsive fallback-mode backend for the Selenium render test, and a workspace-visible `TMPDIR` because Snap Chromium cannot expose its default `/tmp` DevTools profile to Selenium. These are local QA-environment conditions, not tracked-source changes.
- Wave 1 can rely on `make test` as a fast repo-wide lint gate; Wave 6 should still rerun explicit `make lint` plus the AC-25 Docker lanes as planned.

## Todo 7 config test reload idiom

- `test_agent_config.py` copies the existing helper exactly: import `bd_shared.config` dynamically, enter `patch.dict(os.environ, {"BD_CONFIG_FILE": "config.toml", **(env or {})})`, remove requested variables, and return `importlib.reload(config_module)`; `tearDown` reloads the base config to restore shared module state.
- The absent-key cases use `BD_CONFIG_FILE=test_config.toml`, which intentionally has a `[webreport]` section without the knowledge keys and remains untouched by Todo 8. Temporary complete TOML copies add either `knowledge_dir = ""` or a distinct `knowledge_max_topics` override inside `[webreport]`; `BD_CONFIG_FILE` selects those files, so the module reads the section without touching the real local overlay.

## Todo 8 knowledge configuration keys

- Added the five permissive integer `KNOWLEDGE_MAX_*` constants and raw optional `KNOWLEDGE_DIR` to `bd_shared/config.py`; the Docker config tests and both explicit fallback probes pass.

## Todo 9 path-resolution assertions

- Added four red tests covering relative resolution against `config_directory`, unchanged absolute values, absolute `Path` typing, and nonexistent paths.
- The Docker suite reports four passing legacy tests and five failures from the four new methods because the Todo 8 implementation still returns raw strings; the looped absolute-path test contributes two failures.

## Todo 10 knowledge_dir resolution

- `bd_shared/config.py` now imports `Path` and resolves relative `knowledge_dir` values by joining them to the existing `config_directory`; absolute values pass through unchanged, and missing directories require no filesystem access.
- The Docker config lane passed all 8 tests, and `poetry run python parse_data.py --help` exited 0.
- The real-module probe passed with an absolute `Path`; the deliberate naive-copy probe returned a relative `Path` and failed with the expected `AssertionError`. All three `/tmp` scratch files were deleted afterward.

## Todo 11 DATABASE_NAME red tests

- `webreport/backend/test_agent_config.py` currently has 8 `KnowledgeConfigTests` methods and no `DATABASE_NAME` constant exists in `bd_shared/config.py`; the next four tests should therefore fail with `AttributeError` until Todo 12 adds the derived constant.

## Todo 12 DATABASE_NAME derivation

- `DATABASE_NAME = make_url(DATABASE_URL).database` tracks the selected local or Docker URL and performs no database connection; the 12-test backend config lane and data collector import passed.
- The host generator passes with the project-prescribed `PYTHONPATH=.. poetry run python generate_env.py`; a bare invocation from `webreport/` fails because todo 4 removed the old `sys.path` mutation and this shell has no inherited `PYTHONPATH`.

## Todo 13 knowledge model red contracts

- Added the exact six-contract `test_agent_knowledge.py` file; it intentionally imports the not-yet-created `agent.knowledge` module during `setUpClass`.
- The Docker red lane failed with `ModuleNotFoundError: No module named 'agent.knowledge'` and exit 1, while the standalone AST probe printed `PARSED OK` and exited 0.
- The temporary backend probe was deleted after verification; todo 13 evidence is in `13-happy.txt` and `13-failure.txt`.

## Todo 14 knowledge model types

- Created `webreport/backend/agent/knowledge.py` with exactly `KnowledgeError`, `KnowledgeLimits`, `KnowledgeTopic`, and `Knowledge`, using only `from dataclasses import dataclass` at module scope.
- The module is 43 lines, has no `bd_shared` import, and `poetry run ruff check webreport/backend/agent/knowledge.py` passed.
- The direct Docker test and verbose rerun passed all six contracts; the inheritance probe printed `Exception` in the MRO, omitted `ValueError`, and printed `PATH /x/y.md`. Evidence is in `14-happy.txt` and `14-failure.txt`; `_probe_14.py` was deleted afterward.

## Todo 15 knowledge manifest red contracts

- Appended five `KnowledgeManifest` pydantic v2 contract tests to `webreport/backend/test_agent_knowledge.py`: the exact `dataset`/`persona` shape, forbidden `language`, the literal `^[a-z0-9_-]{1,64}$` dataset pattern, non-empty persona, and context-supplied `max_persona_chars` enforcement.
- The Docker test run executed 11 tests and failed with five `AttributeError` errors naming the absent `KnowledgeManifest`; exit status was 1. Evidence is in `15-happy.txt` and `15-failure.txt`.

## Todo 16 KnowledgeManifest model

- Added the closed Pydantic v2 `KnowledgeManifest` schema with the pinned dataset pattern, non-empty persona, native extra-field rejection, and a persona-length validator that reads `max_persona_chars` only from validation context. Docker validation passed all 11 tests and rejected all three invalid probe cases, including `language`.

## Todo 17 load_knowledge red contracts

- Added eight loader contracts inside the existing `KnowledgeTypesTests` class, with every manifest fixture isolated under `tempfile.TemporaryDirectory()`.
- The Linux backend container treated `Manifest.TOML` and `manifest.toml` as distinct: the lowercase-path absence assertion passed before the expected missing-`load_knowledge` `AttributeError` occurred.
- Python 3.11 reports an unterminated final TOML string as `at end of document`, without line or column. The deliberately malformed `[[[` fixture reports `at line 1, column 3`, so the parse-failure contract uses that form and accepts a TOML, line, or column marker without pinning the complete stdlib message.
- The Docker red lane ran 19 tests: all 11 existing tests passed and all eight new tests errored only because `agent.knowledge.load_knowledge` is not implemented yet.

## Todo 18 manifest loading

- `_safe_read_bytes` resolves both the configured folder and requested top-level entry, then permits a read only when the resolved entry is a regular file whose parent is exactly the resolved folder. This allows a symlinked deployment folder while rejecting a `manifest.toml` symlink that targets another directory.
- `load_knowledge` preserves stdlib `TOMLDecodeError` text and Pydantic validation text inside `KnowledgeError`, and supplies `max_persona_chars` through Pydantic validation context before comparing the manifest dataset with the configured database name.
- The Linux backend container supports `Path.symlink_to()` in temporary fixtures; the external-target manifest test failed before implementation and passed with containment enforced.

## Todo 19 topic discovery red contracts

- Every topic fixture uses `# {Title}\n\nSome summary paragraph text.\n`; the ignored-entry case adds `manifest.toml`, `notes.txt`, `.hidden.md`, and `rules.md`, while the C7 case adds `rules.md` plus a real `subdir` created with `.mkdir()`.
- Cardinality fixtures cover zero topics and `topic-a.md`, `topic-b.md`, `topic-c.md` against `max_topics=2`. Stem validation uses uppercase `Rules.md`, and the valid ordered fixture uses exactly `glossary.md`, `rules.md`, and `scoring.md`.

## Todo 20 root-only topic discovery

- Root entries are processed in full-filename UTF-8 byte order with checks in this order: skip `manifest.toml`, skip dot-prefixed entries unconditionally, reject directories, then skip non-`.md` entries. Markdown candidates reuse `_safe_read_bytes`, validate the stem, and contribute to the final count check.
- Title and summary extraction is intentionally a simple placeholder in todo 20; todos 21-22 must replace it with AC-11's strict derivation and limits rather than assuming those rules are already implemented.
- Todo 17's `test_load_knowledge_accepts_database_name_string_and_limits` fixture originally had only a manifest, conflicting with todo 19/20's later invariant that zero topics is invalid. The plan-authorized resolution added one valid topic to that smoke-test fixture; future folder-level invariants should be cross-checked against older fixture shapes.

## Todo 21 strict derivation red contracts

- Decision C3 is represented by exactly seven verbose test methods: bullet (`-`, with `*` and `+` in the same category), ordered list (`1.`), fence (backticks, with `~~~` as the equivalent form), heading (`#`), quote (`>`), table (`|`), and HTML (`<`).
- The Markdown fence fixture is safest as a normal double-quoted Python string, while the repeated TOML fixture keeps the existing single-quoted Python literal so its required TOML double quotes need no escaping beyond the patch format.
- All 13 new tests fail against todo 20's placeholder derivation while the 26 pre-existing tests remain green; pre-heading prose makes both successful-derivation contracts distinguish strict first-heading discovery from the current first-nonblank-line behavior.

## Todo 22 strict title and summary derivation

- `_derive_title_and_summary` selects the first valid ATX heading, strips only its leading heading marker and surrounding whitespace, then joins the first following nonblank block without truncating Markdown content.
- The first summary-block line is rejected when it opens with any C3 marker category; the raised `KnowledgeError` records the document path and marker rule.
- The backend Docker lane passed all 39 tests (26 pre-existing plus 13 strict-derivation tests) with none skipped, and the targeted Ruff check passed.

## Todo 23 size, encoding and ordering red contracts

- Oversize-only is red because `load_knowledge` does not enforce `max_doc_bytes`; no `KnowledgeError` is raised.
- Invalid UTF-8 is red because the raw `UnicodeDecodeError` escapes instead of becoming a file-naming `KnowledgeError`.
- Combined oversize and invalid UTF-8 is red because decoding happens before the absent size guard, proving decision C6 is not implemented yet.
- Full-filename byte ordering is green because todo 20 already sorts topic entries by `candidate.name.encode("utf-8")`.

## Todo 24 document size and UTF-8 enforcement

- `load_knowledge` now rejects document bytes over `max_doc_bytes` before decoding and wraps invalid UTF-8 as a file-naming `KnowledgeError`; the existing full-filename byte sort and tuple construction remain unchanged.
- The backend Docker lane passed all 43 knowledge tests, and the combined 10-bytes-over-limit plus `0xFF` probe reported the size rule with no decode wording.

## Todo 25 system-prompt red contracts

- The byte format is persona with no prefix, one blank line, then each operating rule on its own `- ` line, with no trailing newline. The knowledge branch appends D7 as the seventh rule, then one blank line, `## Knowledge topics`, one blank line, and ordered topic lines; it also has no trailing newline.

## Todo 26 system-prompt composition

- `compose_system_prompt` builds the neutral six-rule prompt without retrieval guidance, while loaded knowledge selects the manifest persona and appends D7 plus the loader-preserved topic order.
- Topic titles ending in `.`, `!`, `?`, `…`, or `:` receive only a separating space before their summary; all other titles receive `. `.
- The backend Docker lane passed all 48 tests, the neutral probe excluded numeric budgets, game wording, and `read_knowledge`, and targeted Ruff passed.

## Todo 27 DB-agnosticism proof

- Added the reusable public `GAME_DOMAIN_FORBIDDEN_STRINGS` tuple and an AC-14 library-catalogue fixture that checks its English persona, catalogue/lending topic lines, and case-insensitive absence of every game-domain term.
- The verbose Docker lane passed all 49 tests on arrival, as expected for this proof todo. The same assertion loop passed the library prompt and raised `AssertionError` on `дурак` for the temporary Russian `Без дураков` persona.
- Todo 28 is a no-op: Todo 27 passed on arrival, no coupling was found in `agent/knowledge.py`, and no production code was changed.

## Todo 29 knowledge-limit red contracts

- All five AC-6 limits now have loader-boundary subtests for zero and positive-float values; `max_topics=True` has a separately named verbose test, while `max_bytes_per_turn` remains outside this todo.
- The current loader produced 11 expected failures: positive floats and the boolean passed through, while zero values reached downstream checks whose errors omitted the actionable `knowledge_max_*` config keys.

## Todo 30 knowledge-limit validation

- Public `validate_limits()` checks `max_title_chars`, `max_summary_chars`, `max_persona_chars`, `max_topics`, and `max_doc_bytes` with `type(value) is int` semantics and a minimum of 1; `max_bytes_per_turn` remains out of scope.
- Invalid values raise `KnowledgeError` naming the exact `[webreport]` TOML key as `knowledge_<field_name>`, for example `knowledge_max_topics`, in both the message and `error.key`.
- Todo 31 registered `TestKnowledge` in the agent aggregator; the final verbose aggregate run collected all 52 knowledge tests.

## Todo 32 shipped skeleton strict contract

- Todos 33-35 must make `/bd_shared/knowledge/bez_durakov` load under the five real `bd_shared.config` defaults as a `Knowledge` with exactly three topic ids in order `glossary`, `rules`, `scoring`, manifest dataset `bez_durakov`, and a non-empty persona.

## Todo 33 knowledge manifest

- Added `bd_shared/knowledge/bez_durakov/manifest.toml` with exactly `dataset` and `persona`; raw TOML parsing and validation against the real `KnowledgeManifest` model both pass.

## Todo 34 schema-derived glossary and scoring documents

- `db.py` defines the requested ORM classes and tables: `Game` (`game_id`, `game_date`, `created_at`), `Team` (`team_id`, `team_name`), `GameTeam` (`game_id`, `team_id`), `Vybor` and `Pairs` (both with `points`), `Chisla` (`task_1` through `task_5`, `total_sum`), `Pref` (`task_1` through `task_7`, `goal`, `points`, `penalty`, `bonus`, `total_sum`), `Razobl` (`task_1` through `task_4`, `total_sum`), `Auction` (four `bid`, `points`, and `rate` field groups plus `total_sum`), and `Mot` (`task_1` through `task_3`, `total_sum`). Each round row also has `game_id` and `team_id`.
- `TeamGameScore` is an ORM model for the `team_game_scores` view with seven per-round `*_points` fields and `total_points`. `GameDataService` exposes the eight retrieval methods listed in `scoring.md`; its code supports retrieval and aggregation, not official gameplay formulas.
- The real Docker loader probe measured `glossary` at 1689 bytes with title length 22 and summary length 93, and `scoring` at 1549 bytes with title length 20 and summary length 115. Both are within the strict 80-character title, 200-character summary, and 65536-byte document limits.
- The shipped skeleton test ran 53 tests and had one expected failure, `2 != 3`, because `rules.md` is still absent. No derivation error occurred for `glossary.md` or `scoring.md`.

## Todo 35 rules skeleton

- Added `bd_shared/knowledge/bez_durakov/rules.md` with a Russian operator-authored placeholder and the seven round headings in schema order.
- The Docker knowledge suite passed all 53 tests. A temporary bullet directly below the title raised a `KnowledgeError` naming `rules.md`; after restoring the paragraph, the suite passed again.

## Todo 36 caller-supplied prompt red contracts

- Added two direct four-argument `build_graph` tests without changing the shared three-argument harness: one checks initial prompt injection, and one scripts a tool-call round trip before checking the second model request.
- The Docker graph suite kept all four pre-existing tests green while both new tests failed with the expected `TypeError` naming `build_graph`; the sentinel is absent from non-test backend source.

## Todo 37 composed prompt injection

- Deleted `agent.graph.SYSTEM_PROMPT`, made `build_graph` require a fourth `system_prompt: str` argument, and closed over that argument so every model call receives it first, including calls after a tool round trip.
- `ReportAgentSystem` now supplies `compose_system_prompt(None)` only at its existing agent-mode graph construction seam. This neutral interim value keeps construction valid until todo 47 threads real loaded `knowledge` through the system; the fallback branch and constructor signature remain unchanged.
- Updated the graph harness, checkpointer helper, and reasoning span call site with explicit test prompts. The exact remaining grep hit is `webreport/backend/test_agent_checkpointer.py:96:        actual_prompt = self.graph_module.SYSTEM_PROMPT`; this intentionally broken prompt contract is the tracked handoff to todo 38.

## Todo 38 byte-exact compose_system_prompt contract

- Re-pointed `TestPromptCases` from the deleted `agent.graph.SYSTEM_PROMPT` constant to `agent.knowledge.compose_system_prompt`, covering both no-knowledge and one-topic loaded-knowledge prompts with UTF-8 byte comparisons.
- The exact Docker lane passed all four tests on arrival because the current implementation already matches both decision-text prompts; the invariant loop also keeps `read_rows` and `mark_report` present while excluding the obsolete `256` and `1024` figures.

## Todo 39 prompt contract reconciliation

- Verified the current `compose_system_prompt` implementation and `TestPromptCases` expected strings byte-for-byte for the neutral and loaded-knowledge D1/D3/D4 contracts; no source or test change was needed.
- The required full `test_agent.py` aggregate passed all 143 tests with exit 0, and `git grep -n "SYSTEM_PROMPT" webreport/backend/` returned no output with exit 1.

## Todo 40-41 conditional knowledge tool registration

- The registration contract is best pinned by comparing the complete ordered name list: no knowledge yields the existing ten, while loaded knowledge requires `read_knowledge` at index 0 and the ten existing tools unchanged after it.
- The todo-40 aggregate was observed red with `TypeError: build_tools() got an unexpected keyword argument 'knowledge'`; the todo-41 aggregate then passed all 144 tests.
- The knowledge-bearing branch defines `read_knowledge` inside `build_tools` so it closes over the loaded `Knowledge`; its lookup and error behavior remains the next tool-contract implementation.

## Todo 42-43 read_knowledge contract

- ToolNode tests use the shipped `/bd_shared/knowledge/bez_durakov` folder, compare the `rules` result to the complete file text, and pin exact unknown-id errors for missing, empty, whitespace, and wrong-case ids.
- `read_knowledge` preserves `topic.text`, matches ids exactly, and builds the available-topic list from the loader-preserved tuple order; it does not mutate graph state.
- The aggregate passed all 148 tests, and the made-up-id probe returned an in-band `str` error without raising; `_probe_43.py` was deleted afterward.

## Todo 44-45 agent package game-domain scan

- The agent-package test walks every `.py` file under `webreport/backend/agent/` with the shared `GAME_DOMAIN_FORBIDDEN_STRINGS` tuple and checks the knowledge-free prompt; the 149-test aggregate passed.
- A temporary `_probe.py` containing the historical `Ты — аналитик данных игр «Без дураков».` persona produced two named failures, then was deleted and the aggregate returned green.
- No residue was found, so todo 45 is an explicit no-op; the fallback `webreport/backend/agents/` package and data tools were untouched. Ruff passed on the agent package and knowledge test.

## Todo 46-47 runtime knowledge threading

- `ReportAgentSystem` accepts the concrete optional `Knowledge`, forwards it only while constructing agent tools, and composes the matching system prompt once before building the graph; explicit `None` preserves the ordered ten-tool catalogue.
- The scripted graph flow reads the shipped `rules` topic, exposes its complete text to the next model call without changing `rows_consumed`, and returns the existing in-band `Tool error:` when that document is used as an invalid report tool name.
- A loaded knowledge object is accepted in fallback mode without building tools, composing an agent prompt, or changing the existing fallback response. The full aggregate passed all 153 tests.

## Todo 48-49 startup knowledge ordering

- `startup_event()` constructs and validates the five configured folder limits unconditionally, so an invalid limit aborts before checking an unset `KNOWLEDGE_DIR` or touching the database.
- When configured, knowledge loads exactly once before database initialization and the LiteLLM probe in both elected modes; startup passes that same object to `ReportAgentSystem`.
- The full system suite passed 77 tests, the agent regression suite passed 153 tests, and the failure probe recorded a completed knowledge load before an immediately raised database-initialization error.

## Todo 50-51 knowledge fallback startup

- Unset and absent knowledge folders are detected after unconditional limit validation but before database initialization; each emits only its exact knowledge warning and passes `None` into agent construction.
- The startup tests inspect the real agent-mode tool binding and graph prompt, proving that warn-and-continue omits `read_knowledge` and uses `compose_system_prompt(None)` without changing mode election.
- Live QA recreated `webreport-backend` with `/nope/missing`, served healthy and successful agent-mode requests, then restored the ignored local config byte-for-byte and recreated a healthy backend using `/bd_shared/knowledge/bez_durakov`.

## Todo 52-53 fail-fast invalid knowledge startup

- Seven startup contracts cover missing/unparseable manifests, unknown keys, dataset-pattern violations, empty/over-long personas, and dataset/database mismatch; each pins the ERROR message, absence of `LLM mode elected`, and untouched service/checkpoint state.
- Catching `KnowledgeError` around the complete pre-database knowledge boundary preserves warn-and-continue behavior while logging the exception's own detail once and re-raising before any checkpoint or probe work.
- Live QA must set `reload = false` temporarily: uvicorn's reload supervisor otherwise remains up after its worker rejects startup. With reload disabled, the invalid `wrong_db` fixture put the backend in `Restarting`, exposed no health listener, and logged both dataset names. The ignored local config was restored to SHA-256 `80766ac2a555d78965a4982eb17cd5224438974f76ef06eeea829ff022a29f7a`, generated env was restored, and `/health` recovered successfully.

## Todo 54-55 startup success logging

- A successful shipped-folder load emits exactly one knowledge-concern INFO record using the manifest dataset and `len(knowledge.topics)`; the unset, missing, and invalid branches cannot reach it.
- The in-process ASGI integration starts the real app with the shipped folder, scripts one `read_knowledge("rules")` tool call, posts one `/api/chat` request, and compares the resulting tool message with the shipped `rules.md` text.
- The startup-order mock delegates to the real loader so it preserves the loaded object's manifest and topics while still recording call order. The final system lane passed all 87 tests; the mechanically captured red and green runs differ and report exits 1 and 0 respectively.

## Todo 59

`compose_system_prompt()` собирает persona манифеста, заданные в коде правила и список тем. Полный текст `KnowledgeTopic.text` остаётся доступен по точному идентификатору только через `read_knowledge`.

В `startup_event()` загрузка и валидация знаний происходят перед `GameDataService`, probe LiteLLM и выбором режима. Сегодня независим от БД лишь путь prompt и знаний; восемь data tools и regex `FallbackInterpreter` всё ещё привязаны к игре.

## Todo 60

- Полный список ключей `[webreport]` в `webreport/README.md` теперь включает каждый ключ из текущего `config.toml` и `knowledge_max_bytes_per_turn = 131072` из C10.
- `knowledge_dir` по умолчанию указывает на поставляемую папку. Отсутствующая папка вызывает только предупреждение, а недействительная прерывает запуск. Корневой README ведёт к операторскому разделу руководства.
- Проверка документации нашла 8 строк с `knowledge_`, отдельно нашла `knowledge_max_bytes_per_turn` и не выявила отсутствующих ключей `[webreport]`.

## Todo 56-57 history serialization regression guard

- Extended `test_reasoning_api.py` with a long `read_knowledge` tool-result turn. `_history_entries` and `GET /api/history` expose exactly the user and final assistant entries, preserve accumulated reasoning, and never expose the document-body sentinel; `POST /api/chat` keeps the data-tool response shape.
- `_history_entries` was already tool-agnostic because it whitelists `HumanMessage` and `AIMessage` rather than tool names, so todo 57 is an explicit no-op. The deliberate leak probe failed at the explicit `assertNotIn` guard, while the reasoning suite passed.
