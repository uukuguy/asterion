"""Sentinel provider that must never be imported by the reference route."""

raise RuntimeError("acme poison provider imported")
