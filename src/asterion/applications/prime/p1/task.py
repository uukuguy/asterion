"""Fixed input and task contract, without seeded implementation or answer."""

P1_INPUT_TUPLE = (3, 7, 11, 17)
P1_TASK_STATEMENT = """Use only Python in the persistent ipython tool. The only
task seeds are input_tuple and this task_statement. There are three independent
turns; wait for the next instruction after each turn. Use exactly one cell per
turn, with no exploratory cells.
Setup: define AffineAccumulator(multiplier, offset) with __call__(value) returning
multiplier * value + offset. Instantiate accumulator from input_tuple[:2]. Write
stage-one.json as UTF-8 canonical JSON (sort_keys=True, separators=(',', ':')) plus
one newline, with keys input (the input tuple as a list) and setup_value (the
accumulator called on input_tuple[2]). Do not define final_result yet.
Verification: in the next turn, read exact stage-one.json bytes and call the same
accumulator on input_tuple[2]. Set stage_one_verified to the dict with keys
object_id (id(accumulator)), probe (the call result), and file_sha256 (SHA-256 of
the bytes). Do not redefine the class/object/file or create final_result.
Continuation: after host compaction and control reconstruction, read the same
file, call the same accumulator on input_tuple[3], and set final_result to that
result plus the setup_value loaded from the file. Do not replace earlier state.
Import only json, hashlib and math, each with its own import statement; use
builtins otherwise. Open relative files inside your assigned
directory. No shell, system/environment access, introspection, or other imports.
Each file write is limited to 4096 UTF-8 bytes, each cell to 16384 written bytes,
and all regular files together to 32768 bytes (at most 32 regular files).
"""

P1_SETUP_PROMPT = P1_TASK_STATEMENT + "\nPerform only the setup turn now."
P1_VERIFICATION_PROMPT = (
    "Perform the independent verification turn from task_statement now."
)
P1_CONTINUATION_PROMPT = "Control reconstruction completed. Perform the continuation turn from task_statement now."
