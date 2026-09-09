"""Regression test for issue #37: self-activation could be silently
refused by ovos-core when cross_activation is disabled.

_activate()/_deactivate() forward whatever message dig_for_message()
returns - which almost always already carries a DIFFERENT skill's
identity in its context (whoever emitted the utterance that led here).
The old code only stamped this plugin's own skill_id into the context
when the key was entirely absent, so payload ("skill_id": self.skill_id)
and context (still the other skill's id) disagreed. ovos-core's
_activate_allowed/_deactivate_allowed compare those two identities and
refuse the request whenever they differ - exactly what happens whenever
cross_activation is off.

These tests emit the activation/deactivation while a message from
another skill is "in flight" (simulated via dig_for_message) and assert
the forwarded message's context agrees with its payload. They fail
against the pre-fix code (context keeps the other skill's id).
"""
from unittest.mock import MagicMock

from conftest import Message, module


def _make_plugin_with_bus():
    p = module.CommonReadingPipeline.__new__(module.CommonReadingPipeline)
    p.skill_id = "ovos-common-reading-pipeline-plugin.andlo"
    p._bus = MagicMock()
    return p


def test_activate_stamps_own_identity_even_when_another_skill_is_in_flight(monkeypatch):
    plugin = _make_plugin_with_bus()
    in_flight = Message("some.other.intent", context={"skill_id": "ovos-skill-grimm-tales.andlo"})
    monkeypatch.setattr(module, "dig_for_message", lambda: in_flight)

    plugin._activate(duration_minutes=5)

    forwarded = plugin.bus.emit.call_args.args[0]
    assert forwarded.context["skill_id"] == plugin.skill_id
    assert forwarded.data["skill_id"] == plugin.skill_id


def test_deactivate_stamps_own_identity_even_when_another_skill_is_in_flight(monkeypatch):
    plugin = _make_plugin_with_bus()
    in_flight = Message("some.other.intent", context={"skill_id": "ovos-skill-grimm-tales.andlo"})
    monkeypatch.setattr(module, "dig_for_message", lambda: in_flight)

    plugin._deactivate()

    forwarded = plugin.bus.emit.call_args.args[0]
    assert forwarded.context["skill_id"] == plugin.skill_id
    assert forwarded.data["skill_id"] == plugin.skill_id


def test_activate_stamps_own_identity_when_no_message_is_in_flight(monkeypatch):
    """No regression on the already-working case: nothing in flight at all."""
    plugin = _make_plugin_with_bus()
    monkeypatch.setattr(module, "dig_for_message", lambda: None)

    plugin._activate(duration_minutes=5)

    forwarded = plugin.bus.emit.call_args.args[0]
    assert forwarded.context["skill_id"] == plugin.skill_id
