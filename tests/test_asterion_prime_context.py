from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import struct
import time
import traceback
import unittest

from asterion.agents.prime.compaction_budget import ModelPrice


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/asterion_prime_p1/v1/context-parity.json"
LAUNCH = "a" * 64
COMMAND = "b" * 64
AUTHORITY = "c" * 64
SECRET = "private-sentinel-prompt-and-summary"


def projection(messages):
    return {
        "format": "asterion.prime-context-projection/v1",
        "system_prompt": "",
        "messages": messages,
    }


def user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def material(custom_instructions=None, summary_text="checkpoint"):
    pre = projection([user(SECRET * 24), user("retained")])
    retained = projection([user("retained")])
    preparation = {
        "first_kept_entry_id": "e1",
        "covered_leaf_id": "e1",
        "messages_to_summarize": projection([user(SECRET * 24)]),
        "turn_prefix_messages": projection([]),
        "is_split_turn": False,
        "previous_summary": None,
        "custom_instructions": custom_instructions,
        "retained_context_projection": retained,
        "retained_message_count": 1,
    }
    base = {
        "protocol": "asterion.prime-context-witness/v1",
        "launch_nonce": LAUNCH,
        "command_nonce": COMMAND,
    }
    proposal = {
        **base,
        "phase": "proposal",
        "authority_sha256": AUTHORITY,
        "first_kept_entry_id": "e1",
        "covered_leaf_id": "e1",
        "preparation": preparation,
        "preparation_sha256": digest(preparation),
        "source_kind": "messages",
        "pre_context_projection": pre,
        "pre_context_json": encode(pre).decode(),
        "pre_context_sha256": digest(pre),
        "main_summary_request": encode(projection([user(SECRET)])).decode(),
        "turn_prefix_summary_request": None,
        "pre_units": len(encode(pre)),
        "private_diagnostics": {"tokensBefore": 123456},
    }
    summary = summary_text
    post = projection(
        [
            {
                "role": "compactionSummary",
                "summary": summary,
                "retained_message_count": 1,
                "custom_instructions": None,
            },
            user("retained"),
        ]
    )
    entry = {
        "type": "compaction",
        "id": "e2",
        "parentId": "e1",
        "timestamp": "2000-01-01T00:00:00.000Z",
        "firstKeptEntryId": "e1",
        "summary": summary,
        "tokensBefore": 123456,
        "fromHook": False,
        "details": {"readFiles": [], "modifiedFiles": []},
    }
    persisted = {
        **base,
        "phase": "persisted",
        "authority_sha256": AUTHORITY,
        "first_kept_entry_id": "e1",
        "covered_leaf_id": "e1",
        "preparation_sha256": digest(preparation),
        "compaction_entry": entry,
        "compaction_entry_sha256": digest(entry),
        "summary": summary,
        "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
        "post_context_projection": post,
        "post_context_json": encode(post).decode(),
        "post_context_sha256": digest(post),
    }
    return proposal, persisted


class ContextMixin:
    def module(self):
        self.assertIsNotNone(
            importlib.util.find_spec("asterion.agents.prime.context"),
            "Prime context witness is missing",
        )
        from asterion.agents.prime import context

        return context


class TestAsterionPrimeContext(ContextMixin, unittest.TestCase):
    def test_context_counter_matches_committed_typescript_observation(self):
        context = self.module()
        fixture = json.loads(FIXTURE.read_text())
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    context.count_rebuilt_context(case["projection"]),
                    case["asterion_units"],
                )
                self.assertEqual(
                    context.encode_prime_context_v1(case["projection"]).decode(),
                    case["canonical_json"],
                )
                self.assertEqual(
                    hashlib.sha256(
                        context.encode_prime_context_v1(case["projection"])
                    ).hexdigest(),
                    case["sha256"],
                )

    def test_counter_rejects_invalid_projection_without_private_errors(self):
        context = self.module()
        good = projection([user(SECRET)])
        for changed in [
            {**good, "extra": SECRET},
            {**good, "system_prompt": "\ud800"},
            projection(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "name": SECRET,
                                "arguments_json": "NaN",
                            }
                        ],
                    }
                ]
            ),
            projection(
                [
                    {
                        "role": "compactionSummary",
                        "summary": SECRET,
                        "retained_message_count": 1.0,
                        "custom_instructions": None,
                    }
                ]
            ),
        ]:
            with (
                self.subTest(value=type(changed)),
                self.assertRaisesRegex(
                    context.PrimeContextError, "^invalid Prime context witness$"
                ),
            ):
                context.count_rebuilt_context(changed)

    def test_witness_requires_real_nonempty_compaction_input(self):
        context = self.module()
        with self.assertRaisesRegex(context.PrimeContextError, "witness"):
            context.validate_compaction_witness(
                {"messages_to_summarize": [], "turn_prefix_messages": []}
            )

    def test_counter_rejects_nonfinite_or_illformed_opaque_argument_strings(self):
        context = self.module()
        for argument in ["1e999", '"\\ud800"', '{"\\ud800":1}']:
            value = projection(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "name": "ipython",
                                "arguments_json": argument,
                            }
                        ],
                    }
                ]
            )
            with (
                self.subTest(argument=argument),
                self.assertRaises(context.PrimeContextError),
            ):
                context.count_rebuilt_context(value)

    def test_exact_material_evidence_is_private_free_and_immutable(self):
        context = self.module()
        proposal, persisted = material()
        saved = deepcopy((proposal, persisted))
        evidence = context.validate_compaction_witness(
            proposal,
            persisted,
            expected_launch_nonce=LAUNCH,
            expected_command_nonce=COMMAND,
        )
        self.assertEqual((proposal, persisted), saved)
        self.assertEqual(evidence.before_context_tokens, proposal["pre_units"])
        self.assertLess(evidence.after_context_tokens, evidence.before_context_tokens)
        public = json.dumps(asdict(evidence))
        self.assertNotIn(SECRET, public)
        self.assertNotIn("checkpoint", public)
        self.assertNotIn("123456", public)
        self.assertEqual(evidence.usage_label, "reservation-charged")

    def test_system_projection_rejects_ambiguous_or_nonfinite_metadata(self):
        context = self.module()
        system = json.loads(FIXTURE.read_text())["cases"][-1]["projection"]["messages"][0]
        for field, value in (
            ("extra", SECRET),
            ("sections", [{"name": "same", "value": "a"}, {"name": "same", "value": None}]),
            ("tools_added_json", '[{"name":"x","name":"y"}]'),
            ("tools_added_json", '[{"name":"x","parameters":{"minimum":1e999}}]'),
            ("tools_removed_json", '{}'),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(context.PrimeContextError):
                context.count_rebuilt_context(projection([{**system, field: value}]))

    def test_system_checkpoint_is_bound_and_preserves_native_order(self):
        context = self.module()
        system = deepcopy(json.loads(FIXTURE.read_text())["cases"][-1]["projection"]["messages"][0])
        proposal, persisted = material()
        proposal["pre_context_projection"]["messages"].insert(0, deepcopy(system))
        proposal["pre_context_json"] = encode(proposal["pre_context_projection"]).decode()
        proposal["pre_context_sha256"] = digest(proposal["pre_context_projection"])
        proposal["pre_units"] = len(encode(proposal["pre_context_projection"]))
        proposal["preparation"]["system_context_projection"] = projection([deepcopy(system)])
        proposal["preparation_sha256"] = digest(proposal["preparation"])
        persisted["preparation_sha256"] = proposal["preparation_sha256"]
        persisted["compaction_entry"]["systemMessage"] = deepcopy(system)
        persisted["compaction_entry_sha256"] = digest(persisted["compaction_entry"])
        persisted["post_context_projection"]["messages"].insert(0, deepcopy(system))
        persisted["post_context_json"] = encode(persisted["post_context_projection"]).decode()
        persisted["post_context_sha256"] = digest(persisted["post_context_projection"])
        context.validate_compaction_witness(proposal, persisted,
            expected_launch_nonce=LAUNCH, expected_command_nonce=COMMAND)
        for mutation in ("missing", "changed", "reordered", "system-only-source"):
            with self.subTest(mutation=mutation):
                p, observed = deepcopy((proposal, persisted))
                if mutation == "missing":
                    del observed["compaction_entry"]["systemMessage"]
                elif mutation == "changed":
                    observed["compaction_entry"]["systemMessage"]["sections"][0]["value"] = "changed"
                elif mutation == "reordered":
                    observed["post_context_projection"]["messages"][:2] = reversed(
                        observed["post_context_projection"]["messages"][:2])
                else:
                    p["preparation"]["messages_to_summarize"] = projection([deepcopy(system)])
                    p["preparation_sha256"] = digest(p["preparation"])
                    observed["preparation_sha256"] = p["preparation_sha256"]
                observed["compaction_entry_sha256"] = digest(observed["compaction_entry"])
                observed["post_context_json"] = encode(observed["post_context_projection"]).decode()
                observed["post_context_sha256"] = digest(observed["post_context_projection"])
                with self.assertRaises(context.PrimeContextError):
                    context.validate_compaction_witness(p, observed,
                        expected_launch_nonce=LAUNCH, expected_command_nonce=COMMAND)

    def test_declared_custom_instructions_are_material_not_context_state(self):
        # Pi carries custom instructions on the `before_compaction` hook event and
        # never on the compaction entry it persists, so a proposal that declares
        # them must still validate: the post-context projection of that entry has
        # no such field, and the declared value is summarization material only.
        # Asserted because the shared fixture exercised only the null case, which
        # is how the requirement went unnoticed until a live run set a value.
        context = self.module()
        proposal, persisted = material(custom_instructions="KERNEL-NOTE-TEXT")
        evidence = context.validate_compaction_witness(
            proposal,
            persisted,
            expected_launch_nonce=LAUNCH,
            expected_command_nonce=COMMAND,
        )
        self.assertNotIn("customInstructions", persisted["compaction_entry"])
        self.assertIsNone(
            persisted["post_context_projection"]["messages"][0]["custom_instructions"]
        )
        self.assertEqual(evidence.before_context_tokens, proposal["pre_units"])

    def test_a_summary_larger_than_what_it_replaces_is_accepted(self):
        # A byte bound on the rebuilt context refused legitimate compactions:
        # a markdown-heavy summary costs more JSON bytes per token than the
        # conversation it replaces, and measured live runs landed on both sides
        # of the bound. The projection equality is the invariant; the summary's
        # own size is Pi's to choose.
        context = self.module()
        proposal, persisted = material(summary_text="S" * 8192)
        after = context.count_rebuilt_context(persisted["post_context_projection"])
        self.assertGreater(after, proposal["pre_units"])
        evidence = context.validate_compaction_witness(
            proposal,
            persisted,
            expected_launch_nonce=LAUNCH,
            expected_command_nonce=COMMAND,
        )
        self.assertEqual(evidence.after_context_tokens, after)

    def test_witness_rejects_identity_digest_boundary_source_and_post_drift(self):
        context = self.module()
        mutations = [
            lambda p, s: p.update(command_nonce="d" * 64),
            lambda p, s: s.update(launch_nonce="d" * 64),
            lambda p, s: p.update(first_kept_entry_id="other"),
            lambda p, s: p.update(pre_context_sha256="0" * 64),
            lambda p, s: p.update(pre_units=1),
            lambda p, s: p["preparation"].update(messages_to_summarize=projection([])),
            lambda p, s: s.update(summary=SECRET),
            lambda p, s: s["compaction_entry"].update(parentId="other"),
            lambda p, s: s["compaction_entry"].update(customInstructions="KERNEL-NOTE-TEXT"),
            lambda p, s: s["post_context_projection"]["messages"].append(user(SECRET)),
            lambda p, s: s.update(extra=SECRET),
        ]
        for mutate in mutations:
            proposal, persisted = material()
            mutate(proposal, persisted)
            with (
                self.subTest(mutation=mutate),
                self.assertRaisesRegex(
                    context.PrimeContextError, "^invalid Prime context witness$"
                ),
            ):
                context.validate_compaction_witness(
                    proposal,
                    persisted,
                    expected_launch_nonce=LAUNCH,
                    expected_command_nonce=COMMAND,
                )


async def send(sock, value):
    raw = encode(value)
    await asyncio.get_running_loop().sock_sendall(
        sock, struct.pack("!I", len(raw)) + raw
    )


async def receive(sock):
    loop = asyncio.get_running_loop()

    async def exact(size):
        result = bytearray()
        while len(result) < size:
            chunk = await loop.sock_recv(sock, size - len(result))
            if not chunk:
                raise EOFError
            result.extend(chunk)
        return bytes(result)

    size = struct.unpack("!I", await exact(4))[0]
    return json.loads(await exact(size))


class TestPrimeContextWitnessSession(ContextMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.context = self.module()
        self.host, self.peer = socket.socketpair()
        self.host.setblocking(False)
        self.peer.setblocking(False)
        self.uncertain = []
        self.session = self.context.PrimeContextWitnessSession(
            self.host,
            launch_nonce=LAUNCH,
            timeout_seconds=0.15,
            mark_uncertain=lambda: self.uncertain.append(True),
        )

    async def asyncTearDown(self):
        if hasattr(self, "session"):
            self.session.close()
            self.peer.close()

    async def test_arm_contains_injected_policy(self):
        await self.session.arm(command_nonce=COMMAND, authority_sha256=AUTHORITY)
        observed = await receive(self.peer)
        self.assertEqual(observed['compaction_policy'], {
            'max_total_tokens': 262144, 'max_frame_bytes': 16777216,
            'max_material_bytes': 65536, 'config_source': 'framework-default'})

    async def test_incoming_frame_header_rejects_before_body_allocation(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        from asterion.services.diagnostics import ResourceLimitExceeded
        self.session.close()
        self.peer.close()
        self.host, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        self.session = self.context.PrimeContextWitnessSession(self.host,
            launch_nonce=LAUNCH, mark_uncertain=lambda: None,
            policy=PrimeCompactionPolicy(max_frame_bytes=8192, max_material_bytes=4096))
        await asyncio.get_running_loop().sock_sendall(self.peer, struct.pack('!I', 8193))
        with self.assertRaises(ResourceLimitExceeded) as caught:
            await self.session._receive()
        self.assertEqual(caught.exception.limit_diagnostic.observed, 8193)
        self.assertEqual(caught.exception.limit_diagnostic.limit, 8192)

    async def test_whole_frame_capacity_and_large_default_frame(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        from asterion.services.diagnostics import ResourceLimitExceeded
        for size in (8191, 8192, 8193, 1024 * 1024 + 1):
            with self.subTest(size=size):
                self.session.close()
                self.peer.close()
                self.host, self.peer = socket.socketpair()
                self.peer.setblocking(False)
                policy = (PrimeCompactionPolicy() if size > 8193 else
                    PrimeCompactionPolicy(max_frame_bytes=8192, max_material_bytes=4096))
                self.session = self.context.PrimeContextWitnessSession(self.host,
                    launch_nonce=LAUNCH, mark_uncertain=lambda: None, policy=policy)
                payload = {'text': 'x' * (size - len(encode({'text': ''})))}
                sending = asyncio.create_task(send(self.peer, payload))
                if size == 8193:
                    with self.assertRaises(ResourceLimitExceeded):
                        await self.session._receive()
                    self.session.close()
                else:
                    self.assertEqual(await self.session._receive(), payload)
                await asyncio.gather(sending, return_exceptions=True)

    async def test_outgoing_capacity_checks_complete_frame_before_write(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        from asterion.services.diagnostics import ResourceLimitExceeded
        self.session.close()
        self.peer.close()
        self.host, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        self.session = self.context.PrimeContextWitnessSession(self.host,
            launch_nonce=LAUNCH, mark_uncertain=lambda: None,
            policy=PrimeCompactionPolicy(max_frame_bytes=8192, max_material_bytes=4096))
        for size in (8191, 8192, 8193):
            with self.subTest(size=size):
                payload = {'text': 'x' * (size - len(encode({'text': ''})))}
                if size > 8192:
                    with self.assertRaises(ResourceLimitExceeded) as caught:
                        await self.session._send(payload)
                    self.assertEqual(caught.exception.limit_diagnostic.observed, size)
                else:
                    reading = asyncio.create_task(receive(self.peer))
                    await self.session._send(payload)
                    self.assertEqual(await reading, payload)

    async def test_legacy_frame_alias_has_one_effective_capacity(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        self.session.close()
        self.peer.close()
        self.host, self.peer = socket.socketpair()
        self.peer.setblocking(False)
        self.session = self.context.PrimeContextWitnessSession(self.host,
            launch_nonce=LAUNCH, mark_uncertain=lambda: None, max_frame_bytes=1048576)
        self.assertEqual(self.session._policy.max_frame_bytes, 1048576)
        with self.assertRaises(self.context.PrimeContextError):
            self.context.PrimeContextWitnessSession(self.host, launch_nonce=LAUNCH,
                mark_uncertain=lambda: None, max_frame_bytes=1048576,
                policy=PrimeCompactionPolicy(max_frame_bytes=2000000))

    async def test_limit_after_approval_retains_typed_error_and_recovery_fence(self):
        from dataclasses import asdict
        from asterion.services.diagnostics import LimitDiagnostic, ResourceLimitExceeded
        await self.arm()
        await self.decision()
        diagnostic = LimitDiagnostic('witness-frame-limit', 'settlement',
            'recovery-required', 17000000, 16777216, 'bytes', 'exact', 'framework-default')
        await send(self.peer, {**self.session._base('limit'), 'limit_diagnostic': asdict(diagnostic)})
        with self.assertRaises(ResourceLimitExceeded) as caught:
            await self.session.receive_persisted(persist=lambda _raw: None)
        self.assertEqual(caught.exception.limit_diagnostic, diagnostic)
        self.assertTrue(self.session.uncertain)

    async def test_local_frame_limit_after_approval_labels_recovery(self):
        from asterion.services.diagnostics import ResourceLimitExceeded
        await self.arm()
        await self.decision()
        await asyncio.get_running_loop().sock_sendall(self.peer, struct.pack('!I', 16777217))
        with self.assertRaises(ResourceLimitExceeded) as caught:
            await self.session.receive_persisted(persist=lambda _raw: None)
        self.assertEqual(caught.exception.limit_diagnostic.phase, 'settlement')
        self.assertEqual(caught.exception.limit_diagnostic.action, 'recovery-required')
        self.assertTrue(self.session.uncertain)

    async def test_authenticated_peer_limit_is_typed_and_malformed_is_protocol_error(self):
        from dataclasses import asdict
        from asterion.services.diagnostics import LimitDiagnostic
        diagnostic = asdict(LimitDiagnostic('witness-frame-limit', 'admission', 'rejected',
            17000000, 16777216, 'bytes', 'exact', 'framework-default'))
        for changes in ({}, {'launch_nonce': 'd' * 64},
                {'limit_diagnostic': {**diagnostic, 'observed': True}},
                {'limit_diagnostic': {**diagnostic, 'extra': 'sentinel'}},
                {'limit_diagnostic': {**diagnostic, 'config_source': 'application'}},
                {'limit_diagnostic': {**diagnostic, 'limit': 16777215}},
                {'limit_diagnostic': {**diagnostic, 'limit_code': 'compaction-token-limit', 'unit': 'tokens'}},
                {'limit_diagnostic': {**diagnostic, 'phase': 'settlement', 'action': 'recovery-required'}}):
            with self.subTest(changes=changes):
                self.session.close()
                self.peer.close()
                self.host, self.peer = socket.socketpair()
                self.peer.setblocking(False)
                self.session = self.context.PrimeContextWitnessSession(self.host,
                    launch_nonce=LAUNCH, mark_uncertain=lambda: None)
                await self.arm()
                await send(self.peer, {**self.session._base('limit'),
                    'limit_diagnostic': diagnostic, **changes})
                args = dict(price=ModelPrice(0, 0),
                        remaining_callbacks=2, deadline=time.monotonic() + 1,
                        reserve=lambda _quote: None)
                if not changes:
                    self.assertFalse(await self.session.receive_proposal_and_decide(**args))
                    self.assertEqual(self.session.last_refusal, LimitDiagnostic(**diagnostic))
                    self.assertFalse(self.session.uncertain)
                    self.assertEqual(self.session._state, 'idle')
                else:
                    with self.assertRaises(self.context.PrimeContextError):
                        await self.session.receive_proposal_and_decide(**args)
                    self.assertTrue(self.session.uncertain)

    async def test_typed_callback_deadline_and_reserve_refusals_preserve_reason(self):
        from asterion.services.diagnostics import LimitDiagnostic, ResourceLimitExceeded
        cases = (
            ({'remaining_callbacks': 1}, 'compaction-callback-limit', 1),
            ({'remaining_callbacks': 0}, 'compaction-callback-limit', 0),
            ({'deadline': time.monotonic() - 1}, 'compaction-deadline', 0),
            ({'reserve': lambda _quote: (_ for _ in ()).throw(ResourceLimitExceeded(
                LimitDiagnostic('prime-parent-token-limit', 'admission', 'rejected',
                                48000, 17, 'tokens', 'exact', 'authority')))},
             'prime-parent-token-limit', 17),
        )
        for index, (overrides, code, limit) in enumerate(cases):
            with self.subTest(code=code, limit=limit):
                await self.session.arm(command_nonce=f'{index + 10:064x}', authority_sha256=AUTHORITY)
                await receive(self.peer)
                self.assertIsNone(self.session.last_refusal)
                proposal = material()[0]
                proposal['command_nonce'] = self.session._nonce
                approved, decision, reserved = await self.decision(proposal, **overrides)
                self.assertFalse(approved)
                self.assertEqual(decision['status'], 'reject')
                self.assertEqual(reserved, [])
                self.assertEqual((self.session.last_refusal.limit_code, self.session.last_refusal.limit), (code, limit))
                self.assertFalse(self.session.uncertain)

    async def test_byte_derived_quote_refusal_is_estimate(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        self.session._policy = PrimeCompactionPolicy(max_total_tokens=100)
        self.session._config_source = 'application'
        await self.arm()
        approved, decision, reserved = await self.decision()
        self.assertFalse(approved)
        self.assertEqual(decision['status'], 'reject')
        self.assertEqual(reserved, [])
        diagnostic = self.session.last_refusal
        self.assertEqual((diagnostic.limit_code, diagnostic.limit, diagnostic.measurement,
                          diagnostic.config_source), ('compaction-token-limit', 100, 'estimate', 'application'))

    async def arm(self):
        await self.session.arm(command_nonce=COMMAND, authority_sha256=AUTHORITY)
        arm = await receive(self.peer)
        self.assertEqual(arm["phase"], "arm")
        self.assertEqual(arm["command_nonce"], COMMAND)

    async def decision(self, proposal=None, **overrides):
        proposal = material()[0] if proposal is None else proposal
        await send(self.peer, proposal)
        reserved = []
        args = dict(
            price=ModelPrice(2_000_000, 4_000_000),
            remaining_callbacks=2,
            deadline=time.monotonic() + 60,
            reserve=lambda quote: reserved.append(quote),
        )
        args.update(overrides)
        approved = await self.session.receive_proposal_and_decide(**args)
        decision = await receive(self.peer)
        return approved, decision, reserved

    async def test_reserves_both_callbacks_before_approval_and_persists_before_ack(
        self,
    ):
        await self.arm()
        approved, decision, reserved = await self.decision()
        self.assertTrue(approved)
        self.assertEqual(decision["status"], "approve")
        self.assertEqual(len(reserved[0].branch_quotes), 2)
        stored = []
        await send(self.peer, material()[1])
        evidence = await self.session.receive_persisted(
            persist=lambda value: stored.append(value)
        )
        self.assertEqual(json.loads(stored[0])["summary"], "checkpoint")
        self.assertEqual((await receive(self.peer))["phase"], "ack")
        self.assertFalse(self.uncertain)
        self.assertEqual(evidence.command_nonce, COMMAND)

    async def test_rejection_prevents_reservation_for_unavailable_authority(self):
        await self.arm()
        approved, decision, reserved = await self.decision(remaining_callbacks=1)
        self.assertFalse(approved)
        self.assertEqual(decision["status"], "reject")
        self.assertEqual(reserved, [])
        self.assertFalse(self.uncertain)

    async def test_persister_receives_retained_immutable_canonical_bytes(self):
        await self.arm()
        await self.decision()
        original = material()[1]
        expected = encode(original)
        retained = []

        def mutating_persister(value):
            retained.append(value)
            try:
                value[0] = 0
            except TypeError:
                pass

        await send(self.peer, original)
        evidence = await self.session.receive_persisted(persist=mutating_persister)
        self.assertEqual((await receive(self.peer))["phase"], "ack")
        self.assertIsInstance(retained[0], bytes)
        self.assertEqual(retained[0], expected)
        original["summary"] = SECRET
        decoded = json.loads(retained[0])
        decoded["summary"] = SECRET
        self.session.close()
        self.assertEqual(retained[0], expected)
        stored_entry = json.loads(retained[0])["compaction_entry"]
        self.assertEqual(digest(stored_entry), evidence.compact_entry_sha256)
        self.assertEqual(
            hashlib.sha256(stored_entry["summary"].encode()).hexdigest(),
            evidence.summary_sha256,
        )

    async def test_noncanonical_proposal_bytes_fence_before_reservation(self):
        for variant in ["whitespace", "key-order"]:
            with self.subTest(variant=variant):
                channel, peer = socket.socketpair()
                peer.setblocking(False)
                uncertain, reserved = [], []
                session = self.context.PrimeContextWitnessSession(
                    channel,
                    launch_nonce=LAUNCH,
                    timeout_seconds=0.15,
                    mark_uncertain=lambda: uncertain.append(True),
                )
                try:
                    await session.arm(command_nonce=COMMAND, authority_sha256=AUTHORITY)
                    await receive(peer)
                    proposal = material()[0]
                    raw = (
                        json.dumps(proposal, ensure_ascii=False, sort_keys=True)
                        if variant == "whitespace"
                        else json.dumps(
                            proposal, ensure_ascii=False, separators=(",", ":")
                        )
                    ).encode()
                    await asyncio.get_running_loop().sock_sendall(
                        peer, struct.pack("!I", len(raw)) + raw
                    )
                    with self.assertRaises(self.context.PrimeContextError):
                        await session.receive_proposal_and_decide(
                            price=ModelPrice(0, 0),
                            remaining_callbacks=2,
                            deadline=time.monotonic() + 1,
                            reserve=reserved.append,
                        )
                    self.assertEqual(reserved, [])
                    self.assertEqual(uncertain, [True])
                finally:
                    session.close()
                    peer.close()

    async def test_noncanonical_persisted_bytes_fence_without_calling_persister(self):
        await self.arm()
        await self.decision()
        raw = json.dumps(material()[1], ensure_ascii=False, sort_keys=True).encode()
        await asyncio.get_running_loop().sock_sendall(
            self.peer, struct.pack("!I", len(raw)) + raw
        )
        stored = []
        with self.assertRaises(self.context.PrimeContextError):
            await self.session.receive_persisted(persist=stored.append)
        self.assertEqual(stored, [])
        self.assertEqual(self.uncertain, [True])

    async def test_authority_rejects_overpriced_quote(self):
        await self.arm()
        quotes = []

        def reserve(quote):
            quotes.append(quote)
            return quote.cost_micro_units <= 125_000

        approved, decision, reserved = await self.decision(
            price=ModelPrice(10**12, 10**12), reserve=reserve,
        )
        self.assertFalse(approved)
        self.assertEqual(decision["status"], "reject")
        self.assertEqual(reserved, [])
        self.assertGreater(quotes[0].cost_micro_units, 125_000)

    async def test_private_persistence_failure_fences_without_ack(self):
        await self.arm()
        await self.decision()
        await send(self.peer, material()[1])

        def fail(_value):
            raise RuntimeError(SECRET)

        with self.assertRaisesRegex(
            self.context.PrimeContextError, "^invalid Prime context witness$"
        ) as failure:
            await self.session.receive_persisted(persist=fail)
        self.assertNotIn(SECRET, "".join(traceback.format_exception(failure.exception)))
        self.assertEqual(self.uncertain, [True])
        self.assertTrue(self.session.uncertain)
        self.assertEqual(await asyncio.get_running_loop().sock_recv(self.peer, 1), b"")

    async def test_missing_persisted_frame_fences(self):
        await self.arm()
        await self.decision()
        with self.assertRaises(self.context.PrimeContextError):
            await self.session.receive_persisted(persist=lambda _value: None)
        self.assertTrue(self.session.uncertain)

    async def test_close_after_approval_preserves_uncertain_obligation(self):
        await self.arm()
        await self.decision()
        self.session.close()
        self.assertTrue(self.session.uncertain)
        self.assertEqual(self.uncertain, [True])

    async def test_async_private_persistence_timeout_fences(self):
        await self.arm()
        await self.decision()
        await send(self.peer, material()[1])

        async def pending(_value):
            await asyncio.sleep(1)

        with self.assertRaises(self.context.PrimeContextError):
            await self.session.receive_persisted(persist=pending)
        self.assertTrue(self.session.uncertain)

    async def assert_absolute_persist_deadline(self, *, asynchronous):
        deadline = time.monotonic() + 0.02
        await self.session.arm(
            command_nonce=COMMAND, authority_sha256=AUTHORITY, deadline=deadline
        )
        await receive(self.peer)
        await self.decision(deadline=deadline)
        await send(self.peer, material()[1])

        async def delayed_async(_value):
            await asyncio.sleep(0.065)

        def delayed_sync(_value):
            time.sleep(0.065)

        with self.assertRaisesRegex(
            self.context.PrimeContextError, "^invalid Prime context witness$"
        ):
            await self.session.receive_persisted(
                persist=delayed_async if asynchronous else delayed_sync
            )
        self.assertTrue(self.session.uncertain)
        self.assertEqual(await asyncio.get_running_loop().sock_recv(self.peer, 1), b"")

    async def test_absolute_deadline_prevents_late_ack_after_sync_persist(self):
        await self.assert_absolute_persist_deadline(asynchronous=False)

    async def test_absolute_deadline_cancels_async_persist_without_ack(self):
        await self.assert_absolute_persist_deadline(asynchronous=True)

    async def test_expired_arm_deadline_never_sends_arm(self):
        with self.assertRaisesRegex(
            self.context.PrimeContextError, "^invalid Prime context witness$"
        ):
            await self.session.arm(
                command_nonce=COMMAND,
                authority_sha256=AUTHORITY,
                deadline=time.monotonic() - 1,
            )
        self.assertEqual(await asyncio.get_running_loop().sock_recv(self.peer, 1), b"")

    async def test_malformed_and_duplicate_frames_fence(self):
        await self.arm()
        raw = encode(material()[0])
        sending = asyncio.create_task(
            asyncio.get_running_loop().sock_sendall(
                self.peer,
                struct.pack("!I", len(raw)) + raw + struct.pack("!I", len(raw)) + raw,
            )
        )
        with self.assertRaises(self.context.PrimeContextError):
            await self.session.receive_proposal_and_decide(
                price=ModelPrice(0, 0),
                remaining_callbacks=2,
                deadline=time.monotonic() + 1,
                reserve=lambda _quote: None,
            )
        self.assertTrue(self.session.uncertain)
        await asyncio.gather(sending, return_exceptions=True)


class TestCompactionMaterialPolicy(ContextMixin, unittest.TestCase):
    def test_material_capacity_is_measured_from_canonical_bytes(self):
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy
        from asterion.agents.prime.summarization import build_summarization_material
        from asterion.services.diagnostics import ResourceLimitExceeded
        context = self.module()
        material = build_summarization_material()
        cap = 12000
        policy = PrimeCompactionPolicy(max_frame_bytes=24000, max_material_bytes=cap)
        initial = len(encode(material))
        for size in (cap - 1, cap, cap + 1):
            with self.subTest(size=size):
                padded = {**material, 'system_prompt': material['system_prompt'] + 'x' * (size - initial)}
                if size <= cap:
                    self.assertEqual(context._validate_summarization(padded, policy=policy), padded)
                else:
                    with self.assertRaises(ResourceLimitExceeded) as caught:
                        context._validate_summarization(padded, policy=policy)
                    self.assertEqual(caught.exception.limit_diagnostic.observed, size)


class TestCompactionInputTokenCeiling(unittest.TestCase):
    """Byte-derived request estimates prove arithmetic, not native token bounds."""

    def test_bytes_are_rounded_up_to_a_token_ceiling(self) -> None:
        from asterion.agents.prime.context import _input_token_ceiling

        for text, expected in (("", 0), ("abcd", 1), ("abcde", 2), ("a" * 13_000, 3_250)):
            with self.subTest(size=len(text)):
                self.assertEqual(_input_token_ceiling(text), expected)

    def test_a_realistic_request_leaves_room_under_the_reservation(self) -> None:
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy, quote_compaction_reservation
        from asterion.agents.prime.context import _input_token_ceiling

        # Observed live: a ~6.9 KB and a ~7.7 KB main request beside a small
        # turn-prefix request, with the price the P1 operator pins.
        for request_bytes in (6_929, 7_721):
            with self.subTest(request_bytes=request_bytes):
                quote = quote_compaction_reservation(
                    branch_input_caps=(_input_token_ceiling("x" * request_bytes), 261),
                    branch_output_caps=(3_276, 3_276),
                    price=ModelPrice(140_000, 280_000),
                    policy=PrimeCompactionPolicy(max_total_tokens=16_000),
                    config_source="application",
                )
                self.assertLessEqual(quote.reserved_tokens, 16_000)

    def test_the_same_request_counted_in_bytes_is_refused(self) -> None:
        # The defect this pins: feeding byte counts in as tokens.
        from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy, quote_compaction_reservation

        with self.assertRaises(ValueError):
            quote_compaction_reservation(
                branch_input_caps=(13_000, 261),
                branch_output_caps=(3_276, 3_276),
                price=ModelPrice(140_000, 280_000),
                policy=PrimeCompactionPolicy(max_total_tokens=16_000),
                config_source="application",
            )


# Removed 2026-09-15 (Phase 4): TestPrimeContextWitnessIntegration drove
# packages/typescript/asterion-prime-extension/test/context-witness-harness.mjs.
# That harness resolved the off-limits Prime Agent checkout, verified its
# compaction lock against it, and imported Prime's compaction internals. (The
# checkout path is spelled nowhere here on purpose: the detachment gate scans
# comments too, so a literal would flag this file.) Phase 1 Task 7 deleted the
# harness as a forbidden execution edge,
# leaving this test red and unobserved because it sat in no targeted gate. The
# detachment spec forbids tests that require a Prime checkout to pass, so the
# test is removed rather than restored. P1's compaction-admission coverage is
# rebuilt against Asterion-owned semantics in Phase 4; the 20 tests above cover
# the same session's framing, timing and fencing behaviour without a checkout.
