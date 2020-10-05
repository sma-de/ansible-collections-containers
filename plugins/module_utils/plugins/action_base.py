#!/usr/bin/env python

# TODO: copyright, owner license
#

"""
TODO module / file doc string
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import abc
import collections
import copy
import re
import traceback

from ansible.module_utils.basic import missing_required_lib
from ansible.errors import AnsibleError, AnsibleInternalError, AnsibleOptionsError
from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems
from ansible.plugins.action import ActionBase, set_fact

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert


KWARG_UNSET = object()
MAGIC_ARGSPECKEY_META = '___args_meta'


def default_param_value(pname, defcfg, ans_varspace):
    if not defcfg:
        raise AnsibleOptionsError(
          "Must set mandatory param '{}'".format(pname)
        )

    # check if we have a match in for ansvars
    ansvars = defcfg.get('ansvar', [])
    for av in ansvars:
        if av in ans_varspace:
            return ans_varspace[av]

    # check if we have a matching envvar
    envvars = defcfg.get('env', [])
    envspace = ans_varspace['ansible_env']

    for e in envvars:
        if e in envspace:
            return envspace[e]

    # use hardcoded fallback
    if 'fallback' in defcfg:
        return defcfg['fallback']

    raise AnsibleOptionsError(
      "No hardcoded fallback for param '{}', set it either directly or"
      " by specifying one of these ansible variables (=> {}) or one of"
      " these environment variables (=> {})".format(pname, ansvars, envvars)
    )


def check_paramtype(param, value, typespec, errmsg):
    if typespec == []:
        # no type restriction ==> noop
        return

    if callable(typespec):
        return typespec(value)

    ctspec = typespec

    if isinstance(typespec, list):
        if len(typespec) > 0 and isinstance(typespec[0], list):
            ctspec = [list]
    else:
        ctspec = [typespec]

    type_match = False

    for xt in ctspec:
        if isinstance(value, xt):
            type_match = True
            break

    if not type_match:
        if not errmsg:
            errmsg = "Must be one of the following types: {}".format(typespec)
        raise AnsibleOptionsError(
          "Value '{}' for param '{}' failed its type"
          " check: {}".format(value, param, errmsg)
        )

    if isinstance(value, list):
        ansible_assert(len(typespec) == 1, 'Bad typespec')
        for vx in value:
            check_paramtype(param, vx, typespec[0], errmsg)


class BaseAction(ActionBase):
    ''' TODO '''

    def __init__(self, *args, **kwargs):
      super(BaseAction, self).__init__(*args, **kwargs)
      self._ansvar_updates = {}
      self._taskparams = {}


    @property
    def argspec(self):
        return {}


    def get_taskparam(self, name):
        return self._taskparams[name]


    def run_other_action_plugin(self, plugin_class, ans_varspace=None, args=None):
        ## TODO: not sure if it is really safe to reuse all this magic ansible interna's for other plugin calls, we need at least to adjust _task.args which again means we need a clean copy of this object at least
        ## note: re-using _task object and imply overwriting args worked, still not sure how safe this is
        self._task.args = args or {}

        tmp = plugin_class(self._task, self._connection, 
            self._play_context, self._loader, self._templar, 
            self._shared_loader_obj
        )

        return tmp.run(task_vars=ans_varspace or self._ansible_varspace)


    def _handle_taskargs(self):
        argspec = copy.deepcopy(self.argspec)

        args_set = copy.deepcopy(self._task.args)

        args_found = {}

        args_meta = argspec.pop(MAGIC_ARGSPECKEY_META, {})

        for (k, v) in iteritems(argspec):
            ## first normalize argspec

            # convert convenience short forms to norm form
            if isinstance(v, collections.abc.Mapping):
                pass  # noop
            elif isinstance(v, tuple):
                tmp = {}

                for i in range(0, len(v)):
                    vx = v[i]

                    if i == 0:
                        tmp['type'] = vx
                    elif i == 1:
                        tmp['defaulting'] = { 'fallback': vx }
                    else:
                        raise AnsibleInternalError(
                          "Unsupported short form argspec tuple: '{}'".format(v)
                        )

                v = tmp

            else:
                ## assume a single value for arg type
                v = { 'type': v }

            # normalize norm form
            ansible_assert('type' in v, 
              "Bad argspec for param '{}': Mandatory type field missing".format(k)
            )

            vdef = v.get('defaulting', None)
            mandatory = not vdef

            ## TODO: min and max sizes for collection types

            # get param
            key_hits = []
            aliases = v.get('aliases', [])
            for x in [k] + aliases:
                ansible_assert(x not in args_found, 
                  "Bad argspec for param '{}': duplicate alias"
                  " name '{}'".format(k, x)
                )

                if x in args_set:
                    key_hits.append(x)
                    pval = args_set.pop(x)
                    args_found[k] = True

            if len(key_hits) > 1:
                raise AnsibleOptionsError(
                  "Bad param '{}': Use either key or one of its aliases"
                  " '{}', but not more than one at a time".format(k, aliases)
                )

            if len(key_hits) == 0: 
                # param unset, do defaulting
                pval = default_param_value(k, vdef, self._ansible_varspace)

            ## at this point param is either set explicitly or by 
            ## defaulting mechanism, proceed with value tests
            check_paramtype(k, pval, v['type'], v.get('type_err', None))

            self._taskparams[k] = pval

        if args_set:
            raise AnsibleOptionsError(
              "Unsupported parameters given: {}".format(list(args_set.keys))
            )

        ## check mutual exclusions:
        for exlst in args_meta.get('mutual_exclusions', []):
            tmp = []

            for x in exlst:

                if x in args_found:
                    tmp.append(x)

                if len(tmp) > 1:
                    raise AnsibleOptionsError(
                      "It is not allowed to set mutual exclusive"
                      " params '{}' and '{}' together".format(*tmp)
                    )


    def get_ansible_var(self, var, default=KWARG_UNSET):
        if default != KWARG_UNSET:
            return self._ansible_varspace.get(var, default)
        return self._ansible_varspace[var]


    def set_ansible_vars(self, **kwargs):
        self._ansvar_updates.update(kwargs)


    @abc.abstractmethod
    def run_specific(self, result):
        ''' TODO '''
        pass


    def run(self, tmp=None, task_vars=None):
        ''' TODO '''

        # base method does some standard chorces like parameter validation 
        # and such, it makes definitly sense to call it (at all and first)
        result = super(BaseAction, self).run(tmp, task_vars)
        result['changed'] = False

        self._ansible_varspace = task_vars

        # handle args / params for this task
        self._handle_taskargs()

        errmsg = None
        error_details = {}

        try:
            self.run_specific(result)

            if self._ansvar_updates:
                # with this to magic keys we can actually update the 
                # ansible var space directly just like set_fact, the first 
                # set the keys but the second is also important to set like 
                # this, otherwise var "foo" is only accessable as 
                # ansible_facts.foo beside many other important distinctions
                result['ansible_facts'] = self._ansvar_updates
                result['_ansible_facts_cacheable'] = False

                ##res = self.run_other_action_plugin(set_fact.ActionModule, **self._ansvar_updates)
                ##return res

                ## note: this fails, pretty sure this only works for "real" modules, not action plugins
                ##modret = self._execute_module(module_name='set_fact',
                ##  module_args=self._ansvar_updates, task_vars=task_vars
                ##)

                ##if modret.get('failed', False):
                ##    error_details['set_fact_result'] = modret
                ##    raise AnsibleInternalError(
                ##        "Updating ansible facts failed"
                ##    )

            return result

        except AnsibleError as e:
            error = e
            stacktrace = traceback.format_exc()

        except ModuleNotFoundError as e:
            error = e
            stacktrace = traceback.format_exc()

            bad_lib = re.search(r"(?i)module named '(.*?)'", e.msg).group(1)

            errmsg = missing_required_lib(bad_lib)

        except Exception as e:
            error = AnsibleInternalError(
               to_native("Unhandled native error {}: {}".format(type(e), e))
            )

            stacktrace = traceback.format_exc()

        error_details['stacktrace'] = stacktrace

        result['failed'] = True
        result['msg'] = errmsg or "{}".format(error)
        result['error'] = "{}".format(error)
        result['error_details'] = error_details
        result['stderr'] = stacktrace

        return result

