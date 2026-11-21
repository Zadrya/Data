# SPDX-License-Identifier: GPL-3.0-or-later
"""The invariants of a built dataset: one failing case per rule, and a mutation check.

``_valid`` is a small document that breaks no rule. Each case in ``FAILING`` changes
it in one place, and must fail with exactly its rule, naming the substance and the
field. ``test_each_rule_is_needed`` removes one rule at a time from the checker and
shows that its case then passes: no other rule catches it, so every rule earns its
place. ``VALID_EDGES`` pins the edges a rule must accept (equal dose neighbours,
min equal to max). The invariants assume a document the schema accepts: the build
validates the schema first.
"""

import copy
from collections.abc import Callable
from typing import Any

import pytest

from tests.test_normalize_real import BASE_FILE, _snapshot
from zadrya_data import invariants
from zadrya_data.base import load_base
from zadrya_data.invariants import Failure, InvariantError, check, require
from zadrya_data.normalize import normalize
from zadrya_data.normalize.names import name_key

type Mutation = Callable[[dict[str, Any]], None]


def _substance(name: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "aliases": [],
        "url": f"https://psychonautwiki.org/wiki/{name}",
        "categories": ["stimulant"],
        "classes": {"psychoactive": [], "chemical": []},
        "roas": [],
        "crossTolerances": [],
        "interactions": {"dangerous": [], "unsafe": [], "uncertain": []},
        "toxicities": [],
    } | extra


def _valid() -> dict[str, Any]:
    alpha = _substance(
        "Alpha",
        aliases=["A1"],
        roas=[
            {
                "route": "oral",
                "dose": {
                    "units": "mg",
                    "thresholdMin": 5,
                    "lightMin": 10,
                    "commonMin": 20,
                    "strongMin": 30,
                    "heavyMin": 40,
                },
                "duration": {"total": {"min": 60, "max": 120}},
                "bioavailability": {"min": 50, "max": 70},
            }
        ],
        tolerance={
            "half": {"text": "1-2 days", "min": 1440, "max": 2880},
            "zero": {"text": "1 week", "min": 10080, "max": 10080},
        },
        crossTolerances=["stimulants"],
        interactions={
            "dangerous": [
                {"kind": "substance", "name": "Beta"},
                {"kind": "group", "groupId": "depressants"},
            ],
            "unsafe": [{"kind": "other", "name": "Grapefruit"}],
            "uncertain": [],
        },
        toxicities=["Low."],
        saferUse=["Start low."],
    )
    beta = _substance(
        "Beta",
        aliases=["B1"],
        roas=[{"route": "insufflated", "dose": {"units": "µg", "commonMin": 1.5}}],
        crossTolerances=["stimulants"],
        interactions={
            "dangerous": [{"kind": "substance", "name": "Alpha"}],
            "unsafe": [],
            "uncertain": [],
        },
    )
    return {
        "schemaVersion": "1.0.0",
        "datasetVersion": "1.0.0",
        "attribution": [
            {"name": "PsychonautWiki", "url": "https://psychonautwiki.org", "license": "CC-BY-4.0"}
        ],
        "categories": [{"id": "stimulant", "name": "stimulant", "description": "Stimulants."}],
        "interactionGroups": [{"id": "depressants", "name": "Depressants", "members": ["Beta"]}],
        "crossToleranceGroups": [
            {"id": "stimulants", "name": "Stimulants", "members": ["Alpha", "Beta"]},
            {"id": "modafinil-analogs", "name": "Modafinil analogs", "members": []},
        ],
        "substances": [alpha, beta],
    }


def _alpha(document: dict[str, Any]) -> dict[str, Any]:
    substance: dict[str, Any] = document["substances"][0]
    return substance


def _beta(document: dict[str, Any]) -> dict[str, Any]:
    substance: dict[str, Any] = document["substances"][1]
    return substance


def _set(path: Callable[[dict[str, Any]], dict[str, Any]], key: str, value: Any) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        path(document)[key] = value

    return mutate


def _dose(document: dict[str, Any]) -> dict[str, Any]:
    dose: dict[str, Any] = _alpha(document)["roas"][0]["dose"]
    return dose


def _total(document: dict[str, Any]) -> dict[str, Any]:
    total: dict[str, Any] = _alpha(document)["roas"][0]["duration"]["total"]
    return total


def _bioavailability(document: dict[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = _alpha(document)["roas"][0]["bioavailability"]
    return block


def _half(document: dict[str, Any]) -> dict[str, Any]:
    half: dict[str, Any] = _alpha(document)["tolerance"]["half"]
    return half


def _drop_symmetric_partner(document: dict[str, Any]) -> None:
    _beta(document)["interactions"]["dangerous"] = []


def _lower_symmetric_partner(document: dict[str, Any]) -> None:
    _beta(document)["interactions"]["dangerous"] = []
    _beta(document)["interactions"]["uncertain"] = [{"kind": "substance", "name": "Alpha"}]


def _missing_target(document: dict[str, Any]) -> None:
    _alpha(document)["interactions"]["unsafe"].insert(0, {"kind": "substance", "name": "Gamma"})


def _self_target(document: dict[str, Any]) -> None:
    _alpha(document)["interactions"]["unsafe"].insert(0, {"kind": "substance", "name": "Alpha"})


def _target_twice(document: dict[str, Any]) -> None:
    _alpha(document)["interactions"]["uncertain"].append({"kind": "other", "name": "grapefruit"})


def _missing_group(document: dict[str, Any]) -> None:
    _alpha(document)["interactions"]["dangerous"][1]["groupId"] = "opioids"


def _missing_member(document: dict[str, Any]) -> None:
    document["interactionGroups"][0]["members"].append("Gamma")


def _missing_cross_tolerance_member(document: dict[str, Any]) -> None:
    document["crossToleranceGroups"][0]["members"].append("Gamma")


def _missing_cross_tolerance_group(document: dict[str, Any]) -> None:
    _alpha(document)["crossTolerances"].append("opioids")


def _listed_by_non_member(document: dict[str, Any]) -> None:
    document["crossToleranceGroups"][0]["members"].remove("Beta")


def _not_listed_by_member(document: dict[str, Any]) -> None:
    _beta(document)["crossTolerances"] = []


def _missing_category(document: dict[str, Any]) -> None:
    _alpha(document)["categories"].append("opioid")


def _repeated_category(document: dict[str, Any]) -> None:
    document["categories"].append(dict(document["categories"][0]))


def _repeated_group(document: dict[str, Any]) -> None:
    document["interactionGroups"].append(
        {"id": "depressants", "name": "Downers", "members": ["Beta"]}
    )


def _repeated_name(document: dict[str, Any]) -> None:
    document["substances"].append(_substance("ALPHA"))


def _alias_repeated(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("a1")


def _member_repeated(document: dict[str, Any]) -> None:
    document["interactionGroups"][0]["members"].append("Beta")


def _alias_is_other_name(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("beta")


def _alias_shared(document: dict[str, Any]) -> None:
    _beta(document)["aliases"].append("a1")


def _alias_is_own_name(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("ALPHA")


def _alias_is_group_name(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("depressants")


def _repeated_item(document: dict[str, Any]) -> None:
    _alpha(document)["toxicities"].append("Low.")


def _repeated_route(document: dict[str, Any]) -> None:
    _alpha(document)["roas"].append({"route": "oral"})


def _greek_mu(document: dict[str, Any]) -> None:
    _beta(document)["roas"][0]["dose"]["units"] = "μg"


def _mass_spelling(document: dict[str, Any]) -> None:
    _dose(document)["units"] = "MG"


def _not_finite(document: dict[str, Any]) -> None:
    _total(document)["max"] = float("inf")


def _not_a_number(document: dict[str, Any]) -> None:
    _bioavailability(document)["min"] = float("nan")


# rule, substance, field (the start of it), mutation
FAILING: dict[str, tuple[str, str | None, str, Mutation]] = {
    "dose-light-below-threshold": (
        "dose-order",
        "Alpha",
        "roas[oral].dose.lightMin",
        _set(_dose, "lightMin", 4),
    ),
    "dose-heavy-below-strong": (
        "dose-order",
        "Alpha",
        "roas[oral].dose.heavyMin",
        _set(_dose, "heavyMin", 29),
    ),
    "duration-min-above-max": (
        "range",
        "Alpha",
        "roas[oral].duration.total",
        _set(_total, "min", 121),
    ),
    "bioavailability-min-above-max": (
        "range",
        "Alpha",
        "roas[oral].bioavailability",
        _set(_bioavailability, "min", 71),
    ),
    "tolerance-min-above-max": ("range", "Alpha", "tolerance.half", _set(_half, "min", 2881)),
    "interaction-not-symmetric": (
        "interaction-symmetric",
        "Alpha",
        "interactions.dangerous",
        _drop_symmetric_partner,
    ),
    "interaction-other-severity": (
        "interaction-symmetric",
        "Alpha",
        "interactions.dangerous",
        _lower_symmetric_partner,
    ),
    "substance-target-missing": (
        "target-exists",
        "Alpha",
        "interactions.unsafe",
        _missing_target,
    ),
    "substance-target-itself": ("target-exists", "Alpha", "interactions.unsafe", _self_target),
    "target-under-two-severities": (
        "target-unique",
        "Alpha",
        "interactions.uncertain",
        _target_twice,
    ),
    "group-target-missing": ("group-exists", "Alpha", "interactions.dangerous", _missing_group),
    "group-member-missing": (
        "member-exists",
        None,
        "interactionGroups[depressants].members",
        _missing_member,
    ),
    "cross-tolerance-member-missing": (
        "member-exists",
        None,
        "crossToleranceGroups[stimulants].members",
        _missing_cross_tolerance_member,
    ),
    "cross-tolerance-group-missing": (
        "cross-tolerance",
        "Alpha",
        "crossTolerances",
        _missing_cross_tolerance_group,
    ),
    "cross-tolerance-not-listed-by-member": (
        "cross-tolerance",
        "Beta",
        "crossTolerances",
        _not_listed_by_member,
    ),
    "cross-tolerance-listed-by-non-member": (
        "cross-tolerance",
        "Beta",
        "crossTolerances",
        _listed_by_non_member,
    ),
    "category-missing": ("category-exists", "Alpha", "categories", _missing_category),
    "category-id-repeated": ("unique-id", None, "categories", _repeated_category),
    "group-id-repeated": ("unique-id", None, "interactionGroups", _repeated_group),
    "name-repeated-without-case": ("unique-name", "ALPHA", "name", _repeated_name),
    "alias-is-another-name": ("unique-alias", "Alpha", "aliases", _alias_is_other_name),
    "alias-shared": ("unique-alias", "Beta", "aliases", _alias_shared),
    "alias-is-own-name": ("unique-alias", "Alpha", "aliases", _alias_is_own_name),
    "alias-is-group-name": ("alias-not-group", "Alpha", "aliases", _alias_is_group_name),
    "alias-repeated": ("unique-alias", "Alpha", "aliases", _alias_repeated),
    "member-repeated": (
        "unique-items",
        None,
        "interactionGroups[depressants].members",
        _member_repeated,
    ),
    "list-item-repeated": ("unique-items", "Alpha", "toxicities", _repeated_item),
    "route-repeated": ("unique-items", "Alpha", "roas", _repeated_route),
    "unit-greek-mu": ("mass-unit", "Beta", "roas[insufflated].dose.units", _greek_mu),
    "unit-other-mass-spelling": ("mass-unit", "Alpha", "roas[oral].dose.units", _mass_spelling),
    "number-infinite": ("finite", "Alpha", "roas[oral].duration.total.max", _not_finite),
    "number-nan": ("finite", "Alpha", "roas[oral].bioavailability.min", _not_a_number),
}


def _zero(document: dict[str, Any]) -> dict[str, Any]:
    zero: dict[str, Any] = _alpha(document)["tolerance"]["zero"]
    return zero


def _append(path: Callable[[dict[str, Any]], Any], value: Any) -> Mutation:
    def mutate(document: dict[str, Any]) -> None:
        path(document).append(value)

    return mutate


def _other_on_both_sides(document: dict[str, Any]) -> None:
    # The reviewer's case: a real substance pair turned into ``other`` on both sides.
    _alpha(document)["interactions"]["dangerous"][0] = {"kind": "other", "name": "Beta"}
    _beta(document)["interactions"]["dangerous"][0] = {"kind": "other", "name": "Alpha"}


def _other_is_an_alias(document: dict[str, Any]) -> None:
    _alpha(document)["interactions"]["unsafe"].append({"kind": "other", "name": "b1"})


def _other_is_a_group(document: dict[str, Any]) -> None:
    _beta(document)["interactions"]["uncertain"].append({"kind": "other", "name": "Depressants"})


def _name_is_a_group(document: dict[str, Any]) -> None:
    document["substances"].append(_substance("Modafinil\u200b Analogs"))


def _composed_and_decomposed_names(document: dict[str, Any]) -> None:
    document["substances"].append(_substance("Caf\u00e9"))
    document["substances"].append(_substance("Cafe\u0301"))


def _alias_with_a_double_space(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("Ice Cream")
    _beta(document)["aliases"].append("ice  cream")


def _alias_with_a_zero_width_space(document: dict[str, Any]) -> None:
    _alpha(document)["aliases"].append("Be\u200bta")


def _catalog_number(document: dict[str, Any]) -> None:
    document["interactionGroups"][0]["weight"] = float("inf")


FAILING |= {
    "tolerance-zero-min-above-max": ("range", "Alpha", "tolerance.zero", _set(_zero, "min", 1e6)),
    "other-is-a-substance-on-both-sides": (
        "other-outside-catalog",
        "Alpha",
        "interactions.dangerous",
        _other_on_both_sides,
    ),
    "other-is-an-alias": (
        "other-outside-catalog",
        "Alpha",
        "interactions.unsafe",
        _other_is_an_alias,
    ),
    "other-is-a-group": (
        "other-outside-catalog",
        "Beta",
        "interactions.uncertain",
        _other_is_a_group,
    ),
    "name-is-a-group-name": ("name-not-group", "Modafinil\u200b Analogs", "name", _name_is_a_group),
    "alias-is-a-group-id": (
        "alias-not-group",
        "Alpha",
        "aliases",
        _append(lambda d: _alpha(d)["aliases"], "Modafinil-Analogs"),
    ),
    "alias-is-a-cross-tolerance-group-name": (
        "alias-not-group",
        "Beta",
        "aliases",
        _append(lambda d: _beta(d)["aliases"], "modafinil  analogs"),
    ),
    "composed-and-decomposed-names": (
        "unique-name",
        "Cafe\u0301",
        "name",
        _composed_and_decomposed_names,
    ),
    "alias-with-a-double-space": (
        "unique-alias",
        "Beta",
        "aliases",
        _alias_with_a_double_space,
    ),
    "alias-with-a-zero-width-space": (
        "unique-alias",
        "Alpha",
        "aliases",
        _alias_with_a_zero_width_space,
    ),
    "safer-use-repeated": (
        "unique-items",
        "Alpha",
        "saferUse",
        _append(lambda d: _alpha(d)["saferUse"], "Start low."),
    ),
    "chemical-class-repeated": (
        "unique-items",
        "Alpha",
        "classes.chemical",
        lambda d: _alpha(d)["classes"].update(chemical=["Phenethylamines"] * 2),
    ),
    "cross-tolerance-repeated": (
        "unique-items",
        "Alpha",
        "crossTolerances",
        _append(lambda d: _alpha(d)["crossTolerances"], "stimulants"),
    ),
    "unit-full-width": (
        "mass-unit",
        "Alpha",
        "roas[oral].dose.units",
        _set(_dose, "units", "\uff4d\uff47"),
    ),
    "unit-mcg": (
        "mass-unit",
        "Beta",
        "roas[insufflated].dose.units",
        lambda d: _beta(d)["roas"][0]["dose"].update(units="mcg"),
    ),
    "number-outside-routes": (
        "finite",
        "Alpha",
        "tolerance.half.max",
        _set(_half, "max", float("inf")),
    ),
    "number-in-a-catalog-list": ("finite", None, "interactionGroups[0].weight", _catalog_number),
}


def _equal_dose_neighbours(document: dict[str, Any]) -> None:
    _dose(document)["lightMin"] = 5
    _dose(document)["heavyMin"] = 30


def _equal_bounds(document: dict[str, Any]) -> None:
    _total(document)["min"] = 120
    _bioavailability(document)["min"] = 70
    _half(document)["min"] = 2880


def _opaque_units(document: dict[str, Any]) -> None:
    _dose(document)["units"] = "mg THC"
    _beta(document)["roas"][0]["dose"]["units"] = "Mg#"


VALID_EDGES: dict[str, Mutation] = {
    "equal-dose-neighbours": _equal_dose_neighbours,
    "equal-bounds": _equal_bounds,
    "opaque-units": _opaque_units,
    "one-sided-range": lambda document: _total(document).pop("min"),
}


def _other_in_full_width(document: dict[str, Any]) -> None:
    # "Beta" in full-width letters: only NFKC makes it the catalog substance.
    _alpha(document)["interactions"]["uncertain"].append(
        {"kind": "other", "name": "\uff22\uff45\uff54\uff41"}
    )


def _other_with_a_zero_width_space(document: dict[str, Any]) -> None:
    # Alpha already lists Grapefruit as unsafe: only removing format characters makes
    # this the same target.
    _alpha(document)["interactions"]["uncertain"].append(
        {"kind": "other", "name": "Grape\u200bfruit"}
    )


# The normalized name key (``_key``) in the ``other`` branches: compared as raw
# strings, both cases would pass.
FAILING |= {
    "other-is-a-substance-in-full-width": (
        "other-outside-catalog",
        "Alpha",
        "interactions.uncertain",
        _other_in_full_width,
    ),
    "other-target-with-a-zero-width-space": (
        "target-unique",
        "Alpha",
        "interactions.uncertain",
        _other_with_a_zero_width_space,
    ),
}


def _mutated(mutation: Mutation) -> dict[str, Any]:
    document = _valid()
    mutation(document)
    return document


def test_the_valid_document_breaks_no_rule() -> None:
    assert check(_valid()) == []
    require(_valid())


def test_every_rule_has_a_failing_case() -> None:
    assert {rule for rule, _, _, _ in FAILING.values()} == set(invariants.RULES)


@pytest.mark.parametrize("case", sorted(FAILING))
def test_each_case_fails_with_its_rule_naming_substance_and_field(case: str) -> None:
    rule, substance, field, mutation = FAILING[case]

    failures = check(_mutated(mutation))

    assert failures, case
    assert {failure.rule for failure in failures} == {rule}
    assert any(
        failure.substance == substance and failure.field.startswith(field) for failure in failures
    ), failures


@pytest.mark.parametrize("case", sorted(FAILING))
def test_each_rule_is_needed(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    rule, _, _, mutation = FAILING[case]
    monkeypatch.setattr(
        invariants, "RULES", {name: f for name, f in invariants.RULES.items() if name != rule}
    )

    assert check(_mutated(mutation)) == []


@pytest.mark.parametrize("case", sorted(VALID_EDGES))
def test_edges_that_stay_valid(case: str) -> None:
    assert check(_mutated(VALID_EDGES[case])) == []


def test_the_error_lists_every_failure_not_just_the_first() -> None:
    document = _valid()
    for case in ("dose-light-below-threshold", "alias-shared", "group-member-missing"):
        FAILING[case][3](document)

    with pytest.raises(InvariantError) as error:
        require(document)

    assert [failure.rule for failure in error.value.failures] == [
        "dose-order",
        "member-exists",
        "unique-alias",
        "unique-alias",
    ]
    message = str(error.value)
    assert message.startswith("the dataset breaks its invariants in 4 place(s):\n")
    assert "  Alpha: roas[oral].dose.lightMin: 4 is below thresholdMin 5 (dose-order)" in message
    assert "  (catalog): interactionGroups[depressants].members: 'Gamma'" in message


def test_failures_are_sorted_and_printable() -> None:
    failure = Failure("unique-alias", "Beta", "aliases", "'a1' is also an alias of Alpha")

    assert str(failure) == "Beta: aliases: 'a1' is also an alias of Alpha (unique-alias)"


def test_the_checker_does_not_change_the_document() -> None:
    document = _mutated(FAILING["alias-shared"][3])
    before = copy.deepcopy(document)

    check(document)

    assert document == before


@pytest.mark.parametrize(
    "recording", ["graphql.json", "graphql-doses.json", "graphql-relations.json"]
)
def test_the_real_base_file_with_each_recording_keeps_every_invariant(recording: str) -> None:
    base = load_base(BASE_FILE)
    document = normalize(base, _snapshot(base, recording)).document

    assert check(document) == []


@pytest.mark.parametrize(
    "name",
    [
        "LSD",
        "Caf\u00e9",
        "Cafe\u0301",
        "Ice  Cream",
        " ice\tcream ",
        "Be\u200bta",
        "AL\u00adPHA",
        "\uff2c\uff33\uff24",
        "\u00b5g",
        "Stra\u00dfe",
        "\u0391MT",
    ],
)
def test_the_invariants_compare_names_as_normalization_does(name: str) -> None:
    assert invariants._key(name) == name_key(name)
