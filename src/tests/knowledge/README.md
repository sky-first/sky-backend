# Knowledge refactor test skeleton

These files are the **executable form** of
`sky-security/docs/KNOWLEDGE_REFACTOR.md` §5 (Test matrix).

Every test in this directory is currently marked
`@pytest.mark.skip(reason="Phase X not yet implemented")` so the
suite stays green during the rename phase. As each phase ships, the
implementing PR removes the `skip` and the test goes red → green
on the same branch. **A test must NOT exist without an `@xfail` or
`@skip` decorator if the feature isn't there yet** — pytest's
collection step reports the count, which is what we use to track
progress.

Phase ordering (matches §8 of the master plan):

| Phase | File | Tests count |
|---|---|---|
| 2 | `test_knowledge_visibility.py` | 10 |
| 2 | `test_knowledge_crud.py` | ~12 |
| 3 | `test_knowledge_mutation_rbac.py` | 14 |
| 4 | `test_promotion_flow.py` | 10 |
| 4 | `test_knowledge_conflicts.py` | 9 |
| 5 | `test_relationships_nn.py` | 6 |
| 6 | `test_knowledge_suggest.py` | 6 |
| 6 | `test_metric_formula_generation.py` | 7 |

Total: 74 backend tests + ~25 frontend tests + 4 e2e = **~100+ tests**
gating Knowledge.

When you start a phase:

1. Open the file for that phase
2. Pick a single test
3. Remove the `@pytest.mark.skip` decorator
4. Run the test — it errors (model doesn't exist yet)
5. Implement until green
6. Repeat for the next test
7. Don't move to the next phase until the previous phase's file has
   zero `skip` markers
