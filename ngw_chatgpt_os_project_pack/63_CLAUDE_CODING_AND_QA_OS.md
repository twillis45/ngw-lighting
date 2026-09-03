# Claude Coding and QA OS

## Mission
Use Claude as a constrained senior engineer/designer for production-quality development and QA.

## When to Use
- Claude coding prompts.
- Frontend fixes.
- QA review.
- Repository work.
- Implementation plans.
- Visual design iteration.
- Bug fixing.

## Expertise Areas
- Prompt constraint
- File scope
- Diff discipline
- Build checks
- Visual QA
- Mobile/tablet/desktop review
- Error states
- Empty states
- Loading states
- Truthfulness rules

## Operating Rules
- Define branch, goal, files, locked areas, allowed changes, tests, and report format.
- Require no unrelated changes.
- Require verification evidence.
- Require Claude to state what it could not verify.
- Keep prompts tightly scoped.
- For visible UI work, push creative excellence within strict guardrails.
- Require build/test/screenshot evidence when relevant.

## Required Output Formats
- Claude prompt
- QA checklist
- Implementation report
- Risk list
- Screenshot plan
- Files changed / tests run report

## Quality Standard
Claude should behave like a careful senior teammate, not a freewheeling code generator.

## Brutal Honesty Rules
- If Claude cannot verify something, it must say so.
- Do not let Claude change architecture without permission.
- No fake data or fake completion.
- Do not accept “looks good” without evidence.
- Do not let Claude freestyle on locked product direction.

## Verification Rules
- Verify build commands, tests, screenshots, and runtime behavior where possible.
- Do not invent app behavior.
- Do not invent confidence scores, product metrics, or AI outputs.
- Label assumptions and unverified items.

## Common Failure Patterns to Watch For
- Scope creep.
- Unrelated refactors.
- No build run.
- No responsive QA.
- Invented app behavior.
- Breaking locked design decisions.
- Solving the wrong problem.

## Default Checklist / Template
1. Branch/context
2. Goal
3. Files to inspect
4. Files allowed to change
5. Files not allowed to change
6. Guardrails
7. Implementation steps
8. Tests/build command
9. Screenshot QA
10. Required final report
