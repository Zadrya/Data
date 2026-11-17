# SPDX-License-Identifier: GPL-3.0-or-later
"""The one base class of every refusal of the signing and release code."""


class ReleaseRejectedError(Exception):
    """A key, a signature, a manifest or a dataset was refused.

    Everything that ``zadrya_data.signing``, ``zadrya_data.manifest`` and
    ``zadrya_data.release_check`` raise on purpose derives from this class, so a
    caller that wants "accepted or not" catches one thing. The subclasses say why.
    """
