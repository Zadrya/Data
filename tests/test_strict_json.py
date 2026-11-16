# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for strict JSON parsing."""

import pytest

from zadrya_data.strict_json import MAX_SAFE_INTEGER, StrictJsonError, loads


def test_plain_json_is_parsed_with_its_number_types() -> None:
    document = loads('{"a": [1, 1.0, 2.5e3, "µg", true, null], "b": {}}')

    assert document == {"a": [1, 1.0, 2500.0, "µg", True, None], "b": {}}
    assert isinstance(document, dict)
    assert [type(item) for item in document["a"][:2]] == [int, float]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_constants_that_are_not_json_are_rejected(constant: str) -> None:
    with pytest.raises(StrictJsonError, match=f"{constant} is not a JSON number"):
        loads(f'{{"min": {constant}}}')


@pytest.mark.parametrize("number", ["1e999", "-1e999", "1.5E+400"])
def test_floats_out_of_range_are_rejected(number: str) -> None:
    with pytest.raises(StrictJsonError) as error:
        loads(f'{{"min": {number}}}')

    assert str(error.value) == f"the number {number} is out of range"


def test_a_repeated_key_is_rejected() -> None:
    with pytest.raises(StrictJsonError) as error:
        loads('{"substances": [{"name": "LSD", "name": "LSA"}]}')

    assert str(error.value) == "the key 'name' appears twice in one object"


def test_the_same_key_in_different_objects_is_fine() -> None:
    assert loads('[{"name": "LSD"}, {"name": "LSA"}]') == [{"name": "LSD"}, {"name": "LSA"}]


def test_deep_nesting_is_an_error_not_a_crash() -> None:
    with pytest.raises(StrictJsonError) as error:
        loads("[" * 100_000 + "]" * 100_000)

    assert str(error.value) == "the document is nested too deeply"


@pytest.mark.parametrize("text", ["", "{", '{"a": 1,}', "{'a': 1}", "[1] 2"])
def test_malformed_text_is_rejected(text: str) -> None:
    with pytest.raises(StrictJsonError, match="not valid JSON"):
        loads(text)


def test_integers_up_to_the_safe_range_of_a_double_are_kept() -> None:
    assert MAX_SAFE_INTEGER == 9007199254740991
    assert loads("[9007199254740991, -9007199254740991, 4288423856]") == [
        MAX_SAFE_INTEGER,
        -MAX_SAFE_INTEGER,
        4288423856,
    ]


@pytest.mark.parametrize("number", ["9007199254740992", "-9007199254740992", "1" + "0" * 399])
def test_integers_outside_the_safe_range_are_rejected(number: str) -> None:
    with pytest.raises(StrictJsonError) as error:
        loads(f'{{"heavyMin": {number}}}')

    assert str(error.value) == f"the integer {number} is outside the safe range of a double"


def test_an_integer_with_more_digits_than_python_converts_is_rejected() -> None:
    with pytest.raises(StrictJsonError, match="an integer has too many digits"):
        loads("9" * 5000)
