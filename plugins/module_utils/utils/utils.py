#!/usr/bin/env python

# TODO: copyright, owner license
#

"""
TODO module / file doc string
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.errors import AnsibleAssertionError


def ansible_assert(condition, error_msg):
    if not condition:
        raise AnsibleAssertionError(error_msg)

