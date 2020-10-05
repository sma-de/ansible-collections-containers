
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import collections
import copy

from ansible.errors import AnsibleOptionsError##, AnsibleError, AnsibleModuleError, AnsibleAssertionError, AnsibleParserError
##from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems, string_types
##from ansible.module_utils.common._collections_compat import MutableMapping
from ansible.utils.display import Display

from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import merge_dicts, template_recursive
from ansible_collections.smabot.base.plugins.module_utils.plugins.action_base import BaseAction, MAGIC_ARGSPECKEY_META


display = Display()


MAGIG_KEY_TOPLVL = '___toplvl____'
MAGIG_KEY_DEFAULTALL = '*'



def _get_inherit_parent(key, vars_access, templater=None, **kwargs):
    res = vars_access

    for k in key.split('.'):
        res = res[k]

    assert isinstance(res, collections.abc.Mapping)

    ##
    ## note: it is important to use a copy here, not the 
    ##   original dict, as the original dict might be 
    ##   inherited on many different places and we dont 
    ##   want to influence other inherits
    ##
    return template_recursive(copy.deepcopy(res), templater)


def _inherits_here(mapping, vars_access, inheritance_keys, **kwargs):
    # handle inheritance for current dict level
    inherit_here = []

    for k in inheritance_keys:
        v = mapping.pop(k, [])

        if not isinstance(v, list):
            v = [v]

        inherit_here += v

    if not inherit_here:
        return mapping

    tmp = {}

    for ih in inherit_here:
        ih = handle_map_inheritance(
            _get_inherit_parent(ih, vars_access, **kwargs), 
            vars_access, inheritance_keys, **kwargs
        )

        merge_dicts(tmp, ih)

    ## note: we want to keep mapping as result, but at the same time 
    ##   it should have priority for overwrites (so must be the 
    ##   right param)
    merge_dicts(tmp, mapping)

    ##
    ## make sure we update mapping inplace while at the same time 
    ## giving the original mapping values higher prio than inherited ones
    ##
    mapping.clear()
    mapping.update(tmp)


# TODO: also copy & pasted from jenkinscfg repo
def handle_map_inheritance(
    mapping, vars_access, inheritance_keys=None, **kwargs
):
    inheritance_keys = inheritance_keys or ['_merge_with']

    _inherits_here(mapping, vars_access, inheritance_keys, **kwargs)

    # check if we need to recurse
    recurse = []

    for (k, v) in iteritems(mapping):

        if isinstance(v, collections.abc.Mapping):
            # definitely recurse for submaps
            v = [v]

        elif isinstance(v, list):
            # we might want to recurse for lists, as they might 
            # contain submaps again
            pass

        else:
            # ignore everything else
            continue

        for vs in v:
            if isinstance(vs, collections.abc.Mapping):
                # recurse for submap, note that without the clear/update 
                # trick above we would have to properly replace old submap 
                # handle with new one here
                handle_map_inheritance(vs, vars_access, 
                    inheritance_keys=inheritance_keys, **kwargs
                )

    return mapping


def recursive_defaulting(mapping, defaultkey, rootlvl=True):
    ignore_subkeys = []

    if rootlvl:
        # initially deep merge defaults into mapping
        defaults = mapping.get(defaultkey, None)

        if not defaults:
            return mapping  ## noop

        merge_dicts(mapping, defaults)
        ignore_subkeys = [defaultkey]

    merge_all = None

    parent_ismap = False

    if isinstance(mapping, collections.abc.Mapping):
        parent_ismap = True
        merge_all = mapping.pop(MAGIG_KEY_DEFAULTALL, None)

    for v in mapping:

        if v in ignore_subkeys:
            continue

        ismap = False

        if parent_ismap:
            # for mapping, 'v' was key until now, but we need only value here
            v = mapping[v]

        ## TODO: also merge to sublists???
        if isinstance(v, collections.abc.Mapping):
            if merge_all:
                merge_dicts(v, merge_all)
            ismap = True

        if ismap or isinstance(v, list):
            recursive_defaulting(v, defaultkey, rootlvl=False)

    return mapping


# TODO: support check mode
# TODO: support async mode??
class ActionModule(BaseAction):

    TRANSFERS_FILES = False

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(*args, **kwargs)
        self._supports_check_mode = False
        self._supports_async = False


    @property
    def argspec(self):
        tmp = super(ActionModule, self).argspec
        tmp.update({
          ##MAGIC_ARGSPECKEY_META: {
          ##   'mutual_exclusions': [
          ##     ['result_var', 'defaulting']
          ##   ],
          ##},

          ## argname
          'result_var': {
            'type': list(string_types), ## function or list of types
            ## ##'type_err': ## custom error message on bad type
            ## 'mandatory': False, ## if unsets defaults to true, except when defaulting is defined

            ## ways to obtain the value if not explicitly specified
            'defaulting': {
              ##'ansvar': ['approle_login_id', 'awxcred_hashivault_approle_id'], ## list of ansible vars / facts to fall back to, sorted by prio descending (first match wins)
##         'env': '', # list of env vars to get value from, like ansvars, prio is lower than ansvars (if an ansvar matches, this is not used)
              ##'fallback': "Hardcoded fallback value, lowest prio"
              'fallback': None,
            },
            ##'aliases': ['foo', 'bar']  ## other alt names for this arg like for upstream ansible stuff
            ##'min': ## for collection args min and max sizes ??
            ##'max': ## 
          },

          ## param def short form for simple non mandatory args: (type, builtin-default)
          'defaulting': ([str, bool], 'defaults'),

          ## other param def sort form for mandatory ones: just the type
          'invars': [[str, dict]],

          ## update: as more or less all standard types are also callable, packing types into list is mandatory now, so outcommented line is illegal and will give bogus results (it will interpret bool as type check function)
          ##'update_facts': (bool, True),
          'update_facts': ([bool], True),

          'hosts': ([[str]], []),
        })

        return tmp


    def run_specific(self, result):
        resvar = self.get_taskparam('result_var')
        defaulting = self.get_taskparam('defaulting')

        toplvl_first = False
        toplvl_last = False

        tmp = self.get_taskparam('invars')

        invars = []
        pos = 0 

        for iv in tmp:

            ## if inmap value is kust a plain string, assume it 
            ##   is the invar name and normalize it to a dict
            if isinstance(iv, string_types):
                iv = {'name': iv}

            n = iv['name']

            ## default resvar to first invar
            if not resvar:
                resvar = n

            if n == MAGIG_KEY_TOPLVL:

                if pos == 0: 
                    toplvl_first = True
                    pos += 1
                    continue

                if pos == len(tmp) - 1:
                    toplvl_last = True
                    pos += 1
                    continue

                raise AnsibleOptionsError(
                    "TOPLEVEL can only be merged first or" \
                  + " last, not somewhere in the middle"
                )

            d = self.get_ansible_var(n, None)

            if not d: 
                if not iv.get('optional', False):
                    raise AnsibleOptionsError(
                        "No invar with given name '{}' was found." \
                      + " Make sure it is defined or set it to" \
                      + " optional if being undefined is acceptable" \
                      + " for this var".format(n)
                    )

                pos += 1
                continue

            pos += 1

            d = template_recursive(d, self._templar)

            # optionally handle internal _merge_with keys
            d = handle_map_inheritance(d, self._ansible_varspace, 
              templater=self._templar
            )

            invars.append({'name': n, 'value': d})

        if not invars:
            # this can happen if only optionals are merged 
            # and all are unset
            return result

        hosts = self.get_taskparam('hosts')
        hostvars = self.get_ansible_var('hostvars')

        if hosts:

            if toplvl_first or toplvl_last:
                AnsibleOptionsError(
                    "TOPLEVEL merging is not supported in hostmode"
                )

            if len(invars) > 1:
                AnsibleOptionsError(
                    "Merging more than one invar is not supported in hostmode atm"
                )

            varname = invars[0]['name']
            invars = []

            resvar = varname

            for h in hosts:
                n = h + '_' + varname

                hv = hostvars[h]

                if varname not in hv:
                    # TODO: do the optional thing from invars??
                    continue

                invars.append({'name': n, 'value': hv[varname]})

        merged = {}
        invars.reverse()

        # first deep merge all "normal" invars in the right order
        for iv in invars:
            merged = merge_dicts(merged, iv['value'])

        # than optionally deep merge toplvl also
        if toplvl_first or toplvl_last:

            dtop = {}

            # for toplvl we only merge keys mentioned in 
            # at least one other invar
            for k in merged:
                if k in self._ansible_varspace:
                    dtop[k] = self.get_ansible_var(k)

            if toplvl_first:
                # toplvl has highest prio, all its explicitly 
                # set values will prevail
                merged = merge_dicts(merged, dtop)
            else:
                # toplvl has lowest prio, anything explicitly set 
                # in another invar will overwrite toplvl value
                merged = merge_dicts(dtop, merged)

        ## optionally handle defaulting
        if defaulting:
            recursive_defaulting(merged, defaulting)

        if resvar != MAGIG_KEY_TOPLVL:
            merged = {resvar: merged}

        # return merged "normaly" a custom value of result dict
        result['merged_var'] = merged

        if self.get_taskparam('update_facts'):
            self.set_ansible_vars(**merged)

        return result

