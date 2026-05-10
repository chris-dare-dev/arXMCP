"""Orchestrator-side utilities (E08_S04+).

The orchestrator composes multi-agent prompts (Lookup, Synthesis,
Verification, Autoformalization) into Anthropic Messages API calls
that share a long-lived prompt cache prefix. v1 ships two
orchestrator-side utilities:

- :mod:`server.orchestrator.id_canon` — :func:`canonicalize_turn`
  rewrites Anthropic-issued non-deterministic ``tool_use_id`` values
  into deterministic counter-based IDs so a tool call in agent A
  doesn't blow agent B's prompt cache prefix.

The orchestrator wiring itself (the loop that calls Anthropic with
`ROLE_PREFIXES[tag]`, the tool-result handling, the 4-agent fan-out)
lands in E08_S05+. The utilities here are pure functions that the
orchestrator imports.
"""
