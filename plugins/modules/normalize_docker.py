#!/usr/bin/python
# -*- coding: utf-8 -*-

# TODO: copyright
# TODO: licence

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
TODO
module: fail
short_description: Fail with custom message
description:
- This module fails the progress with a custom message.
- It can be useful for bailing out when a certain condition is met using C(when).
- This module is also supported for Windows targets.
version_added: "0.8"
options:
  msg:
    description:
    - The customized message used for failing execution.
    - If omitted, fail will simply bail out with a generic message.
    type: str
    default: Failed as requested from task
notes:
    - This module is also supported for Windows targets.
seealso:
- module: ansible.builtin.assert
- module: ansible.builtin.debug
- module: ansible.builtin.meta
author:
- Mirko Wilhelmi (Mirko.Wilhelmi@sma.de)
'''

EXAMPLES = r'''
TODO
- name: Example using fail and when together
  fail:
    msg: The system may not be provisioned according to the CMDB status.
  when: cmdb_status != "to-be-staged"
'''

