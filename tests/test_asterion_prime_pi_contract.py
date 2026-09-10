from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import unittest
from pathlib import Path

from tools.setup_prime_agent import verify_prime_checkout


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/asterion_prime_p1/v1/pi-compaction-contract.json"
PROBE = ROOT / "tools/probe_asterion_prime_compaction.mjs"
LOCK = ROOT / (
    "packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json"
)


class TestAsterionPrimePiContract(unittest.TestCase):
    def calculator(self):
        self.assertIsNotNone(
            importlib.util.find_spec("asterion.agents.prime.compaction_budget"),
            "the shared fail-closed compaction calculator is missing",
        )
        from asterion.agents.prime import compaction_budget

        return compaction_budget

    def test_locked_compaction_contract_and_bound_match_evidence(self) -> None:
        self.assertTrue(PROBE.is_file(), "the locked provider-free probe is missing")
        source = Path(
            os.environ.get("ASTERION_PRIME_SOURCE_ROOT", ROOT / "3th-party/prime-agent")
        ).resolve(strict=True)
        verified = verify_prime_checkout(source)
        self.assertEqual(verified.package_version, "0.7.1")
        completed = subprocess.run(
            ["node", str(PROBE), str(source)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        )
        self.assertEqual(completed.stderr, "")
        observed = json.loads(completed.stdout)
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(observed, expected)
        self.assertEqual(list(observed), sorted(observed))
        self.assertEqual(observed["pi_version"], "0.7.1")
        self.assertFalse(observed["public_prepare_compaction_exported"])
        self.assertTrue(observed["internal_module_beneath_locked_root"])
        self.assertEqual(observed["branches"], ["main-summary", "turn-prefix-summary"])
        self.assertEqual(observed["input_caps"], [4096, 4096])
        self.assertEqual(observed["output_caps"], [3276, 3276])
        self.assertEqual(observed["hook_order"], ["session_before_compact", "session_compact"])
        self.assertEqual(observed["rpc_order"], ["prompt", "compact", "prompt"])
        self.assertEqual(observed["worst_case_reserved_tokens"], 14_744)
        self.assertEqual(observed["worst_case_cost_micro_units"], 42_592)
        self.assertLessEqual(observed["worst_case_reserved_tokens"], 16_000)
        self.assertLessEqual(observed["worst_case_cost_micro_units"], 125_000)
        for branch in observed["branch_evidence"]:
            with self.subTest(branch=branch["branch"]):
                self.assertEqual(branch["request_asterion_units"], 4096)
                self.assertEqual(branch["input_cap"], 4096)
                self.assertEqual(branch["output_cap"], 3276)
                self.assertLessEqual(branch["observed_max_tokens"], branch["output_cap"])
                self.assertRegex(branch["request_sha256"], r"^[0-9a-f]{64}$")
        closure = json.loads(LOCK.read_text(encoding="utf-8"))
        self.assertEqual(list(closure["files"]), sorted(closure["files"]))
        self.assertIn("packages/coding-agent/dist/core/compaction/compaction.js", closure["files"])
        self.assertIn("packages/coding-agent/dist/core/session-manager.js", closure["files"])

    def test_closure_matches_metafile_and_rejects_drift_before_import(self) -> None:
        source = Path(
            os.environ.get("ASTERION_PRIME_SOURCE_ROOT", ROOT / "3th-party/prime-agent")
        ).resolve(strict=True)
        program = r"""
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,rmSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildCompactionLock,verifyCompactionLock,COMPACTION_LOCK} from './tools/build_asterion_prime_compaction_lock.mjs';
const root=process.argv[1];
const expected=JSON.parse(readFileSync(COMPACTION_LOCK,'utf8'));
assert.deepEqual(await buildCompactionLock(root),expected);
assert(Object.isFrozen(verifyCompactionLock(root).lock.files));
const temporary=mkdtempSync(join(tmpdir(),'asterion-compaction-lock-test-'));
try {
  const lockPath=join(temporary,'lock.json');
  for (const mutate of [
    lock=>{lock.package_version='0.7.2'},
    lock=>{lock.files['packages/coding-agent/dist/core/compaction/compaction.js']='0'.repeat(64)},
    lock=>{lock.files['../outside.js']='0'.repeat(64)},
  ]) {
    const changed=structuredClone(expected); mutate(changed);
    writeFileSync(lockPath,JSON.stringify(changed));
    assert.throws(()=>verifyCompactionLock(root,lockPath), /^Error: Pi compaction closure is incompatible$/);
  }
  symlinkSync(root,join(temporary,'alias'));
  assert.throws(()=>verifyCompactionLock(join(temporary,'alias')), /Pi compaction closure is incompatible/);
} finally {rmSync(temporary,{recursive:true,force:true})}
console.log('closure PASS');
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", program, str(source)],
            cwd=ROOT, check=False, capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "closure PASS\n")
        self.assertEqual(completed.stderr, "")

    def test_live_price_uses_the_same_fail_closed_calculator(self) -> None:
        module = self.calculator()
        quote = module.quote_compaction_reservation(
            branch_input_caps=(4096, 4096),
            branch_output_caps=(3276, 3276),
            price=module.ModelPrice(input_per_million=2_000_000, output_per_million=4_000_000),
        )
        self.assertEqual(quote.reserved_tokens, 14_744)
        self.assertEqual(quote.cost_micro_units, 42_592)

    def test_components_round_up_before_the_two_branches_are_summed(self) -> None:
        module = self.calculator()
        quote = module.quote_compaction_reservation(
            branch_input_caps=(4096, 4096),
            branch_output_caps=(3276, 3276),
            price=module.ModelPrice(input_per_million=1, output_per_million=1),
        )
        self.assertEqual(quote.cost_micro_units, 4)
        self.assertEqual(quote.reserved_tokens, 14_744)

    def test_missing_nonfinite_negative_or_ambiguous_prices_fail_closed(self) -> None:
        module = self.calculator()
        for invalid in (None, -1, float("nan"), float("inf"), True, "2", 2.5):
            with self.subTest(price=invalid), self.assertRaises(ValueError):
                module.ModelPrice(input_per_million=invalid, output_per_million=0)
        with self.assertRaises(ValueError):
            module.quote_compaction_reservation(
                branch_input_caps=(4096, 4096), branch_output_caps=(3276, 3276), price=None
            )

    def test_both_branches_caps_and_total_cost_are_required(self) -> None:
        module = self.calculator()
        price = module.ModelPrice(input_per_million=2_000_000, output_per_million=4_000_000)
        for inputs, outputs in (
            ((4096,), (3276, 3276)),
            ((4096, 4096), (3276,)),
            ((True, 4096), (3276, 3276)),
            ((-1, 4096), (3276, 3276)),
            ((9000, 9000), (3276, 3276)),
        ):
            with self.subTest(inputs=inputs, outputs=outputs), self.assertRaises(ValueError):
                module.quote_compaction_reservation(
                    branch_input_caps=inputs, branch_output_caps=outputs, price=price
                )
        with self.assertRaises(ValueError):
            module.quote_compaction_reservation(
                branch_input_caps=(4096, 4096),
                branch_output_caps=(3276, 3276),
                price=module.ModelPrice(input_per_million=100_000_000, output_per_million=100_000_000),
            )

    def test_canonical_projection_counts_content_and_rejects_ambiguous_values(self) -> None:
        self.assertTrue(
            (ROOT / "packages/typescript/asterion-prime-extension/src/context-counter.ts").is_file(),
            "the production canonical context counter is missing",
        )
        program = r"""
import assert from 'node:assert/strict';
import {loadContextCounter} from './tools/build_asterion_prime_compaction_lock.mjs';
const {projectPrimeContext, canonicalJson, countRebuiltContext} = await loadContextCounter();
const original = [{role:'assistant', id:'private-id', timestamp:1, usage:{input:99},
  content:[{type:'thinking',thinking:'想🤖'},{type:'text',text:'done'},
    {type:'toolCall',id:'call-id',name:'ipython',arguments:{z:-0,a:0.125}}]}];
const projected = projectPrimeContext(original, 'system');
assert.equal(projected.messages[0].content[2].arguments_json, '{"a":0.125,"z":0}');
assert.equal(projected.system_prompt,'system');
assert.equal(countRebuiltContext(projected), Buffer.byteLength(canonicalJson(projected),'utf8'));
assert.throws(()=>countRebuiltContext({format:'bad',system_prompt:'',messages:[]}), /invalid Prime context/);
assert.throws(()=>countRebuiltContext({...projected,extra:'unexpected'}), /invalid Prime context/);
assert(!canonicalJson(projected).includes('private-id'));
assert(!canonicalJson(projected).includes('usage'));
assert(Object.isFrozen(projected) && Object.isFrozen(projected.messages[0].content));
original[0].content[1].text='changed';
assert.equal(projected.messages[0].content[1].text,'done');
assert.equal(canonicalJson({'\u{10000}':2,'\ue000':1}),'{"\ue000":1,"\u{10000}":2}');
for (const value of [NaN, Infinity, 0.5, '\ud800', {x:undefined}]) {
  assert.throws(()=>canonicalJson(value), /invalid Prime context/);
}
assert.throws(()=>projectPrimeContext([{role:'unknown',content:[]}]), /invalid Prime context/);
assert.throws(()=>projectPrimeContext([{role:'assistant',content:[{type:'toolCall',name:'x',arguments:{x:NaN}}]}]), /invalid Prime context/);
const covered=projectPrimeContext([
 {role:'user',content:[{type:'image',mimeType:'image/png',data:'aGk='}]},
 {role:'toolResult',toolName:'ipython',isError:false,content:[{type:'text',text:'ok'}]},
 {role:'bashExecution',command:'pwd',output:'result',exitCode:0,cancelled:false,truncated:false},
 {role:'compactionSummary',summary:'summary',retainedMessageCount:2},
]);
assert.equal(covered.messages[0].content[0].byte_length,2);
assert.equal(covered.messages[0].content[0].sha256.length,64);
assert.equal(covered.messages[1].tool_name,'ipython');
assert.equal(covered.messages[2].exit_code,0);
assert.equal(covered.messages[3].retained_message_count,2);
const empty=projectPrimeContext([], 'system');
const excluded=projectPrimeContext([
 {role:'bashExecution',command:'secret-command',output:'secret-output',exitCode:0,cancelled:false,truncated:false,excludeFromContext:true},
 ...['session_slash_command','session_slash_command_result','compaction_outcome'].map(customType =>
  ({role:'custom',customType,content:`excluded-${customType}`})),
], 'system');
assert.deepEqual(excluded.messages, []);
assert.equal(countRebuiltContext(excluded), countRebuiltContext(empty));
const included=projectPrimeContext([
 {role:'bashExecution',command:'pwd',output:'visible-output',exitCode:0,cancelled:false,truncated:false,excludeFromContext:false},
 {role:'custom',customType:'heartbeat_prompt',content:'visible-custom'},
], 'system');
assert.equal(included.messages.length, 2);
assert(countRebuiltContext(included) > countRebuiltContext(empty));
console.log('projection PASS');
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", program],
            cwd=ROOT, check=False, capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "projection PASS\n")
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
