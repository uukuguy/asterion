from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
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


def material():
    pre = projection([user(SECRET * 24), user("retained")])
    retained = projection([user("retained")])
    preparation = {
        "first_kept_entry_id": "e1",
        "covered_leaf_id": "e1",
        "messages_to_summarize": projection([user(SECRET * 24)]),
        "turn_prefix_messages": projection([]),
        "is_split_turn": False,
        "previous_summary": None,
        "custom_instructions": None,
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
    summary = "checkpoint"
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

    async def test_expired_deadline_and_overpriced_quote_reject(self):
        await self.arm()
        approved, decision, reserved = await self.decision(
            price=ModelPrice(10**12, 10**12)
        )
        self.assertFalse(approved)
        self.assertEqual(decision["status"], "reject")
        self.assertEqual(reserved, [])

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


class TestPrimeContextWitnessIntegration(
    ContextMixin, unittest.IsolatedAsyncioTestCase
):
    async def test_python_admits_and_privately_persists_real_locked_pi_compaction(self):
        context = self.module()
        node = shutil.which("node")
        self.assertIsNotNone(node)
        harness = (
            ROOT
            / "packages/typescript/asterion-prime-extension/test/context-witness-harness.mjs"
        )
        host, peer = socket.socketpair()
        uncertain, stored, reserved = [], [], []
        session = context.PrimeContextWitnessSession(
            host,
            launch_nonce=LAUNCH,
            timeout_seconds=5,
            mark_uncertain=lambda: uncertain.append(True),
        )
        child = await asyncio.create_subprocess_exec(
            node,
            str(harness),
            json.dumps({"descriptor": peer.fileno(), "timeoutMs": 5000}),
            cwd=ROOT,
            pass_fds=(peer.fileno(),),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        )
        peer.close()
        try:
            await session.arm(command_nonce=COMMAND, authority_sha256=AUTHORITY)
            self.assertTrue(
                await session.receive_proposal_and_decide(
                    price=ModelPrice(2_000_000, 4_000_000),
                    remaining_callbacks=2,
                    deadline=time.monotonic() + 30,
                    reserve=reserved.append,
                )
            )
            evidence = await session.receive_persisted(persist=stored.append)
            stdout, stderr = await asyncio.wait_for(child.communicate(), 10)
            self.assertEqual(child.returncode, 0)
            self.assertEqual(stderr, b"")
            result = json.loads(stdout)
            self.assertEqual(
                (result["calls"], result["appends"], result["error"]), (2, 1, None)
            )
            self.assertEqual(len(reserved), 1)
            self.assertEqual(len(stored), 1)
            checkpoint = json.loads(stored[0])
            self.assertEqual(
                checkpoint["compaction_entry"]["summary"], checkpoint["summary"]
            )
            self.assertLess(
                evidence.after_context_tokens, evidence.before_context_tokens
            )
            self.assertFalse(uncertain)
            self.assertNotIn("checkpoint", json.dumps(asdict(evidence)))
        finally:
            session.close()
            if child.returncode is None:
                child.kill()
                await child.communicate()
