
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from ansible.errors import AnsibleOptionsError, AnsibleModuleError##, AnsibleError
####from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems##, string_types

from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBase, NormalizerBase, NormalizerNamed
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR



class DockInstEnvHandler(NormalizerBase):

    def __init__(self, plugin, *args, **kwargs):
        super(DockInstEnvHandler, self).__init__(*args, **kwargs)
        self._pluginref = plugin


    @property
    def config_path(self):
        return ['environment']


    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        def handle_shellers(shellmap, env_keys, resmap):
            for (k, v) in iteritems(shellmap):
                if k in env_keys:
                    raise AnsibleOptionsError(
                      "duplicate environment key '{}'".format(k)
                    )

                modret = self._pluginref.exec_module('shell', 
                  modargs={'cmd': v}
                )

                env_keys.append(k)
                resmap[k] = modret['stdout']

        constenv = get_subdict(my_subcfg, ['static'], default_empty=True)
        env_keys = list(constenv.keys())

        proxy = cfg.get('proxy', None)

        if proxy:
            ## if proxy is set, copy proxy vars to env
            proxy = proxy.get('vars', None)

            ansible_assert(proxy, 
              "bad docker config, proxy set but proxy vars are empty"
            )

            for (k, v) in iteritems(proxy):
                if k in env_keys:
                    raise AnsibleOptionsError(
                      "duplicate environment key '{}'".format(k)
                    )

                constenv[k] = v
                env_keys.append(k)

        dynenv = my_subcfg.get('dynamic', None)

        if not dynenv:
            ## no dynamic cfg set, nothing to do
            return my_subcfg

        tmp = {}

        for (k, v) in iteritems(dynenv.get('expand', {})):
            # use standard env shelling mechanism for expanding env vars
            tmp[k] = 'echo "{}"'.format(v)

        resmap = {}

        handle_shellers(tmp, env_keys, resmap)
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

