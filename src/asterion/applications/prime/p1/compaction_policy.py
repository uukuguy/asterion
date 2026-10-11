"""The single P1 compaction preset, within its existing total authority."""

from asterion.agents.prime.compaction_budget import PrimeCompactionPolicy


P1_COMPACTION_RESERVED_TOKENS = 48000
P1_COMPACTION_COST_MICROS = 125000
P1_COMPACTION_POLICY = PrimeCompactionPolicy()
