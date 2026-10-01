"""Simple tests for the `jev` library.

These exercise jev's *offline* seams — no TYPESAFE_API_KEY or network needed:

- The mock seam: a `@jev.fn` body that returns a fully-built model instance
  skips the API call entirely and returns that instance.
- The state builder: `jev.builder(fn)` runs the body's state construction and
  `jev.state_payload(marker)` reads what `fn.state(...)` carried, so you can
  unit-test how a decision's state is assembled without any API call.
- Compile-time validation: unsupported field types raise at decoration time.
"""

from typing import Literal

import jev
import pytest
from pydantic import BaseModel, Field


class Triage(BaseModel):
    department: Literal["billing", "technical", "sales"]
    is_urgent: bool
    severity: int = Field(ge=1, le=5)


@jev.fn
def triage(ticket: str) -> Triage:
    """A customer support ticket to triage.

    {{ ticket }}
    """
    # Mock seam: returning a built model skips the API call. In production the
    # body would be body-less (`...`) and Jev would fill these fields.
    if "charged twice" in ticket:
        return Triage(department="billing", is_urgent=True, severity=4)
    return triage.state()  # body-less: rendered docstring is the state


def test_mock_seam_returns_built_model():
    """A body that returns a model instance is returned verbatim, no API call."""
    result = triage("I was charged twice!")
    assert isinstance(result, Triage)
    assert result.department == "billing"
    assert result.is_urgent is True
    assert result.severity == 4


def test_state_builder_renders_docstring_template():
    """`builder(fn)` + `state_payload` inspect the state with no API call."""
    marker = jev.builder(triage)("please help, my app crashes")
    # body-less branch -> state() with no value -> payload is None
    assert jev.state_payload(marker) is None


def test_fn_state_with_value_carries_payload():
    """`fn.state(value)` builds a marker whose payload is that value."""

    class Flag(BaseModel):
        ok: bool

    @jev.fn
    def check(x: int) -> Flag:
        """ignored when state(value) is used"""
        return check.state({"doubled": x * 2})

    marker = jev.builder(check)(21)
    assert jev.state_payload(marker) == {"doubled": 42}


def test_unsupported_field_type_raises_at_decoration():
    """Jev generates no text, so a `str` field is rejected when decorated."""
    with pytest.raises(TypeError, match="unsupported type"):

        class Bad(BaseModel):
            name: str  # not bool / Literal / Enum / constrained int|float

        @jev.fn
        def who(x: str) -> Bad:
            """{{ x }}"""
            ...


def test_score_field_needs_bounds():
    """An int score field must be constrained with Field(ge=..., le=...)."""
    with pytest.raises(TypeError, match="constrain it with Field"):

        class Unbounded(BaseModel):
            n: int  # no ge/le

        @jev.fn
        def rate(x: str) -> Unbounded:
            """{{ x }}"""
            ...
