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
import uuid

##from ansible.errors import AnsibleOptionsError##, AnsibleError, AnsibleModuleError, AnsibleAssertionError, AnsibleParserError
####from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems, string_types
####from ansible.module_utils.common._collections_compat import MutableMapping
##from ansible.utils.display import Display

from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import merge_dicts, get_subdicts, set_subdict
from ansible_collections.smabot.base.plugins.module_utils.plugins.action_base import BaseAction##, MAGIC_ARGSPECKEY_META
from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert
from ansible_collections.smabot.base.plugins.action import merge_vars



class DefaultSetterBase(abc.ABC):

    def __init__(self, normalizer_fn=None):
        self.normalizer_fn = normalizer_fn

    def __call__(self, *args, **kwargs):
        tmp = self._get_defval(*args, **kwargs)

        normfn = self.normalizer_fn

        if normfn:
            tmp = normfn(tmp) 

        return tmp

    @abc.abstractmethod
    def _get_defval(self, cfg, my_subcfg, cfgpath_abs):
        pass


class DefaultSetterConstant(DefaultSetterBase):

    def __init__(self, value, **kwargs):
        super(DefaultSetterConstant, self).__init__(**kwargs)
        self.my_value = value

    def _get_defval(self, cfg, my_subcfg, cfgpath_abs):
        return self.my_value


class DefaultSetterMappinKey(DefaultSetterBase):

    def __init__(self, **kwargs):
        super(DefaultSetterMappinKey, self).__init__(**kwargs)

    def _get_defval(self, cfg, my_subcfg, cfgpath_abs):
        return cfgpath_abs[-1]


class NormalizerBase(abc.ABC):

    def __init__(self, default_setters=None, sub_normalizers=None):
        self.sub_normalizers = sub_normalizers
        self.default_setters = default_setters

    @property
    def config_path(self):
        ## the "path" / config key chain this normalizer is responsible for
        None

    def __call__(self, *args, **kwargs):
        return self.normalize_config(*args, **kwargs)


    def _handle_default_setters(self, cfg, my_subcfg, cfgpath_abs):
        defsets = self.default_setters

        if not defsets:
            return my_subcfg

        for (k, v) in iteritems(defsets):

            ## as the name implies default_setters are only active 
            ## when key is not set explicitly
            if k in my_subcfg: continue

            my_subcfg[k] = v(cfg, my_subcfg, cfgpath_abs)
        
        return my_subcfg


    def _handle_sub_normalizers(self, cfg, my_subcfg, cfgpath_abs):
        subnorms = self.sub_normalizers

        if not subnorms:
            return my_subcfg

        for sn in subnorms:
            sn(my_subcfg, cfg, cfgpath_abs)

        return my_subcfg


    ## can be overwritten in sub classes
    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        return my_subcfg

    def _handle_specifics_postsub(self, cfg, my_subcfg, cfgpath_abs):
        return my_subcfg


    def normalize_config(self, config, global_cfg=None, cfgpath_abs=None):
        cfgpath = self.config_path
        ansible_assert(
            (global_cfg and cfgpath) or (not global_cfg and not cfgpath), 
            "only for root normalizer element global_cfg can be unset"
        )

        global_cfg = global_cfg or config
        cfgpath_abs = cfgpath_abs or []

        ## note: we cannot iterate "inplace" here, as we also modify 
        ##   the dict inside the loop, we solve this by tmp saving 
        ##   iterator first as list
        sub_dicts = list(get_subdicts(config, cfgpath))
        for (subcfg, subpath) in sub_dicts:

            sp_abs = cfgpath_abs[:]

            if subpath:
                sp_abs += subpath

            self._handle_default_setters(global_cfg, subcfg, sp_abs)
            self._handle_specifics_presub(global_cfg, subcfg, sp_abs)
            self._handle_sub_normalizers(global_cfg, subcfg, sp_abs)
            self._handle_specifics_postsub(global_cfg, subcfg, sp_abs)

            if subpath:
                set_subdict(config, subpath, subcfg)

        return config


class NormalizerNamed(NormalizerBase):

    def __init__(self, *args, **kwargs):
        defsets = kwargs.setdefault('default_setters', {})
        defsets[self.name_key] = DefaultSetterMappinKey()

        super(NormalizerNamed, self).__init__(*args, **kwargs)

    @property
    @abc.abstractmethod
    def name_key(self):
        pass



class ConfigNormalizerBase(BaseAction):

    def __init__(self, normalizer, *args, **kwargs):
        self.normalizer = normalizer
        super(ConfigNormalizerBase, self).__init__(*args, **kwargs)


    @property
    @abc.abstractmethod
    def my_ansvar(self):
        pass

    @property
    def merge_args(self):
        return {
          'invars': [self.get_taskparam('config_ansvar')],
        }


    @property
    def argspec(self):
        tmp = super(ConfigNormalizerBase, self).argspec

        tmp.update({
          'config': ([collections.abc.Mapping], {}),
          'config_ansvar': (list(string_types), self.my_ansvar),
          'merge_vars': ([bool, collections.abc.Mapping], True),
        })

        return tmp


    def run_specific(self, result):
        cfg = self.get_taskparam('config')
        cfgvar = self.get_taskparam('config_ansvar')

        if not cfgvar and not cfg:
            raise AnsibleOptionsError(
              "If param 'config_ansvar' is unset, param 'config' must be set"
            )

        ma = self.merge_args
        mv = self.get_taskparam('merge_vars')

        if mv and ma:
            ## do var merging / inheriting and defaulting, 
            ##   do this always before the normalisation
            if isinstance(mv, collections.abc.Mapping):
                merge_dicts(ma, mv)

            ma['result_var'] = merge_vars.MAGIG_KEY_TOPLVL
            ma['update_facts'] = False

            ans_vspace = None

            if cfg:
                ## caller explicitly provided a cfg as param, use 
                ##   it instead of getting the config from specified 
                ##   cfgvars, as var merging always operates on ansvars 
                ##   not directly on values, we will create a tmp ansvar 
                ##   for our cfg, use uuid as name to avoid clashes
                tmp = str(uuid.uuid4())
                ma['invars'][0] = tmp
                ans_vspace[tmp] = cfg

            cfg = self.run_other_action_plugin(
              merge_vars.ActionModule, ans_varspace=ans_vspace, args=ma
            )

            cfg = cfg['merged_var']

        elif cfgvar and not cfg:
            ## no merging and no explicit cfg param, obtain 
            ##   cfg from defined cfgvar
            cfg = self.get_ansible_var(cfgvar)

        ## do domain specific normalization
        ansible_assert(self.normalizer, 
            "bad normalizer module: normalizer class hierarchy undefined"
        )

        cfg = self.normalizer(cfg)

        ## return merged "normaly" a custom value of result dict
        result['normalized'] = cfg

        ## update ansible var directly
        if cfgvar:
            self.set_ansible_vars(**{cfgvar: cfg})

        return result

