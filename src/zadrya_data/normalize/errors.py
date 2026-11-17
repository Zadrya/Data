# SPDX-License-Identifier: GPL-3.0-or-later
"""The error of a normalization that cannot go on."""


class NormalizationError(ValueError):
    """The inputs contradict each other or the schema in a way no rule covers.

    Normalization reports what it drops or repairs and carries on. It raises only when
    carrying on would mean guessing: an unknown route name, two substances that end up
    with one name, a snapshot that does not belong to the base file.
    """
