"""Formatting instructions for the React chat; visual blocks travel in message.content."""

import json
from pathlib import Path

# Synthetic examples are also parsed by the frontend contract tests.
VISUAL_EXAMPLES = json.loads(
    Path(__file__).with_name("answer_visual_examples.json").read_text(encoding="utf-8")
)
VISUAL_PROMPT = """

## Visual answers in this chat
The chat renders version 1 JSON objects inside fenced Markdown blocks whose language
is dig-visual. Place a block on its own between paragraphs exactly where it is useful.
Use cards for a summary of key metrics; use a line/area chart for time trends or a bar
chart for category comparisons. Prefer these visuals for requests about dynamics,
comparisons or metric summaries, unless the user requests text only. Keep ordinary
questions concise. Explain the main finding in prose; do not just emit a visual.
Use at most 4 visual blocks per answer. Do not wrap the whole answer in a code fence.
The application owns styling, colors and interactions inside these blocks. Inside a
dig-visual block emit data only: no HTML, JavaScript, CSS, image URLs or chart-library
options. Other tools' file attachments remain separate from this inline visual format.

Every block requires version:1, type, title (up to 120 characters), and source (up to
240 characters, an accurate human-readable data source). Optional subtitle (240)
should identify period and granularity; optional note (500) must disclose sampling,
limits, missing data or other caveats when applicable. Answer labels in the user's language.
Only use values you actually obtained through tools or explicit values the user gave;
computed metrics must follow explained arithmetic. Example values below are synthetic,
never facts about the user's project. If values are unavailable, say so; do not draw
plausible-looking trends, fabricate comparison percentages or substitute zero for unknown.
Read the needed rows before building a visual and still follow the mark_report rule
for analytics handles. A visual is presentation, not another data source or a tool call.

type:"metrics": items is an array of 1–6 objects, each with key, label (80), value
(a JSON number or null), and optionally format (number/percent/duration; default number),
unit (up to 16 characters, only with format:number), change_percent (JSON number),
comparison (up to 120 characters describing the real baseline; REQUIRED with change_percent),
sentiment (good/bad/neutral, default neutral). Never assume an increase is beneficial;
use good/bad only when the project goal supports this interpretation. Optional trend
contains 2–60 observed numeric or null values in chronological order and REQUIRES
trend_label (up to 120 characters identifying its period). Do not sum daily unique
users to obtain period uniques. Do not invent a trend to decorate a card.

type:"chart": kind is line/area/bar; x_key identifies the category/date field;
optional x_label names it. series contains 1–4 {key,label} objects and data contains
1–120 row objects. Each row must contain a UNIQUE nonempty string category under x_key
(up to 100 characters) and a JSON number or explicit null for EVERY series key.
Every series must have at least one observed numeric value. Dates use ISO format and
chronological order; include missing expected time buckets as null so gaps stay visible.
All series share one vertical axis: compare only compatible units. Optional block-level
format and unit follow the same rules as cards. Percent values are in percentage units
(3.8 means 3.8%, not 380%); duration values are seconds. Bar charts start at zero.
If there are too many rows, request suitable aggregation or clearly label a top-N subset;
do not silently truncate a trend. Use a Markdown table when a visual would mislead.

All keys must start with a lowercase ASCII letter and contain only lowercase letters,
digits or underscores, at most 48 characters; no dots, brackets, constructor or prototype.
Keys within a block must be distinct, including x_key. Keep the SAME metric key across
answers and blocks so colors stay consistent. Prefer users, visits, pageviews, revenue,
conversions, conversion_rate and bounce_rate when those metrics actually match the data.
Numbers must be finite JSON numbers with absolute value at most 1e15. A block must fit
within 64,000 characters. Never place number strings with spaces or % inside numeric fields.

These two examples show the exact syntax; replace all synthetic values and labels:
""" + "\n\n".join(
    "```dig-visual\n" + json.dumps(example, ensure_ascii=False, separators=(",", ":")) + "\n```"
    for example in VISUAL_EXAMPLES
)
