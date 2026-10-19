# Strict outline structure

The constrained entrypoint and the strict branch of smart generation use the
`strict-outline-v5` workflow. Original generation is unchanged.
Strict routing requires complete substantive per-page content assignments;
partial page descriptions use original mode. Completeness excludes missing
cover, agenda, transition and ending pages. Routing does not depend on whether the task
is creation, editing or beautification, nor whether structural pages are missing.

## Final page count

| Final count | Structure |
| --- | --- |
| 3–5 | Cover, content, ending |
| 6–8 | Cover, agenda, content, ending |
| 9+ | Cover, agenda, chapter transition/content, ending |

All supplementary pages count toward the final total. Large decks start their
first chapter with a transition on page 3. Every transition must introduce
actual content in the same section. Existing special pages are reused.

Page-count priority is configured settings, then explicit prompt counts, then
inference from supplied content and missing structure. Configured counts replace
lower-priority prompt counts rather than requiring both simultaneously. Raw
prompt counts remain in `page_count_resolution` for inspection. Inference is
not a final-count constraint: supplementary pages and count-band changes must
be included. Unsatisfiable configured counts report a conflict without merging
or dropping independent user pages.

## Workflow

1. The outline model interprets the complete requirements. It returns exact
   source segments, semantic content points, special-role evidence, roles,
   and exact/range/approximate count intent. Each supplied page remains one
   independent source. A special role needs explicit semantic evidence in the
   source and at most one content point; otherwise the page becomes content.
   Code checks the evidence/point-count contract, not natural-language keywords.
   Source segments must cover all substantive input without losing text.
   Page labels may be metadata outside the quoted body; whitespace changes and
   separators do not invalidate extraction. Any unmatched prose or numbers are
   returned verbatim in repair feedback, including global instructions.
2. JSON becomes ordered textual requirements with stable source IDs and
   predecessor relationships, without original page labels or fixed positions.
   The model directly generates the complete outline, using effective count
   requirements and the final-count structure rules. There is no intermediate
   candidate-plan call or frozen page plan.
3. Code checks the generated outline's actual count, structural roles, source
   coverage, independent pages, relative order, chapters and preserved content.
   Agenda points must cover actual chapter titles in order. Transitions must
   start real chapters. Noncompliance feedback includes the actual count,
   applicable band and specific missing/misplaced structure. The next model
   call optimizes the full outline and may insert/remove/reposition supplemental
   pages. The optimized outline is checked again before persistence.

Model calls get at most two retries. Invalid JSON or malformed responses get
repair prompts. Technical failure falls back to the original generator with
`constraint_validation.skipped=true` and `passed=false`. Structural/count
conflicts or loss of user content after repair (including during extraction) fail explicitly; they do not
silently truncate pages or pretend strict validation succeeded.
Both project views display a warning for saved or newly generated fallback results.

Metadata stores `page_requirements`, `page_count_resolution`, `structure_band` and the
generation operation ID. Each output slide has `source_ids` and `origin`.
Implementation lives in `strict_outline_requirements.py` and
`constrained_outline_generation_service.py`. Successful strict generation takes
two model calls (extraction and direct outline); smart mode adds routing.

## Regression case

`tests/fixtures/bank_developer_requirements.json` contains all 18 user-provided
page bodies. Tests reconstruct the numbered request without a production
regex parser. Scripted model responses conservatively keep all 18 as content.
Adding a cover, agenda, ending and one transition yields 22 pages; three
transitions yield 24. Special-page reuse is covered separately.
Neither count nor these roles are hardcoded in production. A live model may
choose another valid interpretation or chapter grouping.

The tests check full-text preservation (including numbers and names), reuse of
special pages, short source 8, chapter transitions, count-band boundaries,
count conflicts, order-only requirements, special-role guards, chapter/agenda
consistency, retries, repair and fallback. They use
model stubs and do not certify live-model semantic accuracy.

`tests/fixtures/strict_outline_label_regression.json` captures the actual input
and final failed extraction response from project
`9c01b685-cc94-44c6-8fc6-7d6d9217e49b`. Its model returned labels separately
from page bodies. Regression tests replay that response, check specific missing
context feedback, and verify that content-validation failures cannot silently
trigger original generation. No provider configuration is included.

Run:

```text
python -m pytest -q tests/test_constrained_outline_generation_service.py tests/test_outline_normalization_service.py tests/test_outline_workflow_service.py
```
