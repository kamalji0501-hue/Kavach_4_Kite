# Generic Reference System

Purpose: Maintain a reusable, project-agnostic structure for design-to-code continuity.

Use this system before coding, during coding, and during validation.

## Files In This Folder

1. FEATURE_REFERENCE.csv
- Master feature register for status, ownership, dependencies, and acceptance criteria.

2. DECISION_REGISTER.md
- Timestamped decision log with rationale and downstream impact.

3. DISCUSSION_CAPTURE.md
- Session-by-session summary of what was discussed, what was locked, and what remains open.

4. CODING_HANDOFF_CHECKLIST.md
- Implementation readiness checklist to confirm requirements are clear before coding.

5. TECHNICAL_CHANGE_INDEX.md
- Technical routing index for where functions/features live and which files to update together.

6. FUNCTION_OWNERSHIP_INDEX.md
- Function-level lookup index to jump directly to owning files during rapid change cycles.

## Recommended Workflow

0. Technical intake first:
- Start with FUNCTION_OWNERSHIP_INDEX.md and TECHNICAL_CHANGE_INDEX.md before reading broader files.

1. During design discussion:
- Add or update rows in FEATURE_REFERENCE.csv.
- Add a decision note in DECISION_REGISTER.md.
- Add one session entry in DISCUSSION_CAPTURE.md.

2. Before coding:
- Run CODING_HANDOFF_CHECKLIST.md.
- Confirm each target feature has clear acceptance criteria.

3. During coding:
- Update feature status from DESIGN_LOCKED_NOT_CODED to CODED or CODED_NOT_INTEGRATED.
- Capture implementation notes and unresolved risks.

4. After coding and testing:
- Mark validation outcome and evidence paths.
- Add final discussion entry with result and next action.

## Status Vocabulary

- CODED
- CODED_NOT_INTEGRATED
- DESIGN_LOCKED_NOT_CODED
- PENDING_DESIGN
- OPS_VALIDATION_PENDING

## Notes

- Keep this generic structure unchanged.
- Project-specific trackers can map to this structure as needed.
- Do not delete historical rows; append updates for traceability.
