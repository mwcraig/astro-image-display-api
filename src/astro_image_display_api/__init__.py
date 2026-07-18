# SPDX-FileCopyrightText: 2025-present Matt Craig <mattwcraig@gmail.com>
#
# SPDX-License-Identifier: BSD-3-Clause

try:
    from ._version import version as __version__
except ImportError:
    __version__ = ""

from .interface_definition import *  # noqa: F403
