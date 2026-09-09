"""Game-agnostic prompt for the native P7 solve preset."""


P7_SOLVE_PROMPT = """Solve the current interactive puzzle level.
Use only the ipython tool. Inspect every observation programmatically, maintain
explicit hypotheses about objects and controls, test uncertainty with short
experiments, compare before/after state, reject no-ops and death paths, and
revise contradicted hypotheses. Continue until status reports one completed
level or the fixed run limit terminates the attempt. Do not assume a known map,
object identity, target coordinate, or action sequence."""


__all__ = ("P7_SOLVE_PROMPT",)
