
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import collections

from ansible.errors import AnsibleOptionsError, AnsibleModuleError##, AnsibleError
####from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems##, string_types

from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBase, NormalizerBase, NormalizerNamed
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR


class DockInstEnvHandler(NormalizerBase):

    def __init__(self, *args, **kwargs):
        super(DockInstEnvHandler, self).__init__(*args, **kwargs)


    @property
    def config_path(self):
        return ['environment']


    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        def add_new_envkey(k, v, resmap, keylist):
            if k in keylist:
                raise AnsibleOptionsError(
                  "duplicate environment key '{}'".format(k)
                )

            resmap[k] = v
            keylist.append(k)

        def handle_shellers(shellmap, env_keys, resmap):
            for (k, v) in iteritems(shellmap):
                modret = self.pluginref.exec_module('shell', 
                  modargs={'cmd': v}
                )

                add_new_envkey(k, modret['stdout'], resmap, env_keys)

        constenv = get_subdict(my_subcfg, ['static'], default_empty=True)
        constenv.clear()

        env_keys = []

        for xenv in self.pluginref.get_taskparam('extra_envs'):
            for (k, v) in iteritems(xenv):
                add_new_envkey(k, v, constenv, env_keys)

        dynenv = my_subcfg.get('dynamic', None)

        modpath = self.pluginref.get_taskparam('modify_path')

        if not dynenv and not modpath:
            ## no dynamic cfg set, nothing to do
            return my_subcfg

        resmap = {}

        tmp = {}

        for (k, v) in iteritems(dynenv.get('expand', {})):
            # use standard env shelling mechanism for expanding env vars
            tmp[k] = 'echo "{}"'.format(v)

        if modpath:
            # get currently set path on image to build
            tmp['PATH'] = 'echo "{}"'.format('$PATH')

        handle_shellers(tmp, env_keys, resmap)

        # handle modifying system $PATH for new image
        if modpath:
            presents = modpath.get('present', [])
            absents = modpath.get('absent', [])

            new_path = []

            if modpath.get('presets', True):
                known_paths = {}

                for p in presents:
                    known_paths[p] = True

                for p in absents:
                    known_paths[p] = False

                for p in resmap['PATH'].split(':'):
                    known = known_paths.pop(p, None)

                    if known is None or known:
                        # keep paths not explicitly handled, and also
                        # the ones in present obviously
                        new_path.append(p)
                    ##else: # absentee paths, dont keep them

                ## append all present paths not already set on this at the end
                ## TODO: support more positioning modes for new paths??
                for (k, v) in iteritems(known_paths):
                    if v:
                        new_path.append(k)

            else:
                new_path = presents

            resmap['PATH'] = ':'.join(new_path)

        shellers = dynenv.get('shell', {})
        handle_shellers(shellers, env_keys, resmap)

        constenv.update(resmap)
        return my_subcfg



class ActionModule(ConfigNormalizerBase):

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(
            DockInstEnvHandler(self), *args, **kwargs
        )

        self._supports_check_mode = False
        self._supports_async = False


    @property
    def my_ansvar(self):
        return None

    @property
    def supports_merging(self):
        return False

    @property
    def argspec(self):
        tmp = super(ActionModule, self).argspec

        tmp.update({
          'extra_envs': ([[collections.abc.Mapping]], []),
          'modify_path': ([collections.abc.Mapping], {}),
        })

        return tmp

