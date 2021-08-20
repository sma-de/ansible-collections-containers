

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'community'
}

import collections

from ansible.errors import AnsibleFilterError, AnsibleOptionsError
from ansible.module_utils.six import string_types
from ansible.module_utils.common._collections_compat import MutableMapping
from ansible.module_utils._text import to_text, to_native

from ansible_collections.smabot.base.plugins.module_utils.plugins.plugin_base import MAGIC_ARGSPECKEY_META
from ansible_collections.smabot.base.plugins.module_utils.plugins.filter_base import FilterBase

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible_collections.smabot.containers.plugins.module_utils.common import add_deco

from ansible.utils.display import Display


display = Display()



class AppendContEnvFilter(FilterBase):

    FILTER_ID = 'append_contenv'

    @property
    def argspec(self):
        tmp = super(AppendContEnvFilter, self).argspec

        tmp.update({
          'new_vars': ([collections.abc.Mapping],),
          'strategy': (list(string_types), 'replace'),
          'stratopts': ([collections.abc.Mapping], {}),
        })

        return tmp


    def _do_strat_basic(self, conflict_handler, key, curvars, newvars, **kwargs):
        if key not in curvars:
            # if key is also new, we dont have a conflict
            return newvars[key]

        oldval = curvars[key]
        newval = newvars[key]

        return conflict_handler(key, oldval, newval, **kwargs)


    def do_strat_write_once(self, key, oldval, newval, **kwargs):
        if oldval == newval:
            # if for some strange reason oldval and newval 
            # are identical, there is no reason to error out I guess
            return oldval

        ## write once does not allow resetting existing keys, 
        ## so it simply generates an error when a write conflict occours
        raise AnsibleFilterError(
           "Trying to overwrite already existing var key '{}' with"\
           " current value '{}' with value '{}', but selected"\
           " write_once strategy forbids resetting keys.".format(
              k, oldval, newval
           )
        )


    def do_strat_keep_first(self, key, oldval, newval, **kwargs):
        ## keep first strat prefers old over new value
        return oldval


    def do_strat_replace(self, key, oldval, newval, **kwargs):
        ## replace strat always prefers newval over oldval
        return newval


    def do_strat_combine(self, key, oldval, newval, 
        old_first=True, combiner=' ', **kwargs
    ):
        ## combine strat combines old and new value
        if old_first:
            return oldval + combiner + newval
        return newval + combiner + oldval


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        curvars = value.setdefault('vars', {})
        newvars = self.get_taskparam('new_vars')

        strat = self.get_taskparam('strategy')
        stratopts = self.get_taskparam('stratopts')

        tmp = getattr(self, 'do_strat_' + strat, None)

        if not tmp:
            raise AnsibleOptionsError(
               "Unsupported strategy '{}'".format(strat)
            )

        strat = tmp

        for (k, v) in newvars.items():
            curvars[k] = self._do_strat_basic(
              strat, k, curvars, newvars, **stratopts
            )

        return value


class DecoAddFilter(FilterBase):

    FILTER_ID = 'add_deco'

##    def __init__(self, *args, **kwargs):
##        super(FilterBase, self).__init__(*args, **kwargs)

    @property
    def argspec(self):
        tmp = super(DecoAddFilter, self).argspec

        tmp.update({
          'key': (list(string_types),),
          'value': (list(string_types),),
          'add_env': ([list(string_types)], []),
          'add_label': ([list(string_types)], []),
          'only_when_empty': ([bool], False),
        })

        return tmp


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        ##display.vvv("[{}] :: url after modification: {}".format(
        ##   type(self).FILTER_ID, value
        ##))

        add_deco(value, self.get_taskparam('key'), 
           self.get_taskparam('value'),
           add_env=self.get_taskparam('add_env'),
           add_label=self.get_taskparam('add_label'),
           only_when_empty=self.get_taskparam('only_when_empty')
        )

        return value


class DecoToEnvFilter(FilterBase):

    FILTER_ID = 'deco_to_env'

    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        res = {}

        for k, v in value.get('deco', {}).items():
            envkeys = v.get('addto', {}).get('env', [])

            for ek in envkeys:
                res[ek] = v['value']

        return res


class DecoToLabelsFilter(FilterBase):

    FILTER_ID = 'deco_to_labels'

    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        res = {}

        for k, v in value.get('deco', {}).items():
            label_keys = v.get('addto', {}).get('labels', [])

            for lk in label_keys:
                res[lk] = v['value']

        return res



# ---- Ansible filters ----
class FilterModule(object):
    ''' filter related to container building '''

    def filters(self):
        res = {}

        for f in [AppendContEnvFilter, DecoAddFilter, DecoToEnvFilter, DecoToLabelsFilter]:
            res[f.FILTER_ID] = f()

        return res

