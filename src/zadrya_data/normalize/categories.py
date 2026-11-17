# SPDX-License-Identifier: GPL-3.0-or-later
"""Categories: the list of the dataset, and the categories of each substance.

The list comes from the base file. A category's ``id`` and ``name`` are both the base
name, which must be a slug; its ``color`` and ``url`` are presentation and are left
out. A base substance keeps its base categories. A substance that only the API has
gets categories derived from its psychoactive classes through ``CLASS_TO_CATEGORY``;
a class that is not in the table is reported and gives no category.
"""

import re
from typing import Any

from zadrya_data.base import BaseFile, BaseSubstance
from zadrya_data.graphql import ApiSubstance
from zadrya_data.normalize import text
from zadrya_data.normalize.errors import NormalizationError
from zadrya_data.normalize.report import Kind, Report
from zadrya_data.schema import SchemaName, load_schema

# Psychoactive class of the API, exactly as written there, to category id. The API
# mixes singular and plural, so both spellings of each class are listed.
CLASS_TO_CATEGORY = {
    "Antidepressant": "antidepressant",
    "Antidepressants": "antidepressant",
    "Antipsychotic": "antipsychotic",
    "Antipsychotics": "antipsychotic",
    "Cannabinoid": "cannabinoid",
    "Cannabinoids": "cannabinoid",
    "Deliriant": "deliriant",
    "Deliriants": "deliriant",
    "Depressant": "depressant",
    "Depressants": "depressant",
    "Dissociative": "dissociative",
    "Dissociatives": "dissociative",
    "Entactogen": "entactogen",
    "Entactogens": "entactogen",
    "Eugeroic": "eugeroic",
    "Eugeroics": "eugeroic",
    "Hallucinogen": "hallucinogen",
    "Hallucinogens": "hallucinogen",
    "Hypnotic": "hypnotic",
    "Hypnotics": "hypnotic",
    "Nootropic": "nootropic",
    "Nootropics": "nootropic",
    "Oneirogen": "oneirogen",
    "Oneirogens": "oneirogen",
    "Opioid": "opioid",
    "Opioids": "opioid",
    "Psychedelic": "psychedelic",
    "Psychedelics": "psychedelic",
    "Stimulant": "stimulant",
    "Stimulants": "stimulant",
}


def category_list(base: BaseFile) -> list[dict[str, Any]]:
    """Return the categories of the dataset, in the order of the base file."""
    slug = re.compile(load_schema(SchemaName.SUBSTANCES)["$defs"]["slug"]["pattern"])
    categories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category in base.categories:
        description = text.line(category.description)
        if not slug.search(category.name) or category.name in seen:
            raise NormalizationError(
                f"the base category '{category.name}' is not a slug or appears twice"
            )
        if description is None:
            raise NormalizationError(
                f"the base category '{category.name}' has a description that is not valid text"
            )
        seen.add(category.name)
        categories.append({"id": category.name, "name": category.name, "description": description})
    return categories


def substance_categories(
    name: str,
    base: BaseSubstance | None,
    api: ApiSubstance | None,
    known: set[str],
    report: Report,
) -> list[str]:
    """Return the category ids of one substance, without repeats, in source order."""
    result: list[str] = []
    if base is not None:
        for category in base.categories:
            if category not in known:
                report.add(
                    Kind.CATEGORY_UNKNOWN,
                    f"the base category '{category}' is not in the category list",
                    substance=name,
                )
            elif category not in result:
                result.append(category)
        return result

    classes = (api.classes.psychoactive if api and api.classes else None) or ()
    for psychoactive in classes:
        mapped = CLASS_TO_CATEGORY.get(text.strip(psychoactive))
        if mapped is None or mapped not in known:
            report.add(
                Kind.CLASS_UNMAPPED,
                f"the psychoactive class '{psychoactive}' has no category",
                substance=name,
            )
        elif mapped not in result:
            result.append(mapped)
    derived = ", ".join(result) if result else "none"
    report.add(
        Kind.CATEGORIES_DERIVED,
        f"categories derived from the psychoactive classes of the API: {derived}",
        substance=name,
    )
    return result
