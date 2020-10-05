
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import NormalizerBase
##from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY


class ConfigNormerProxy(NormalizerBase):

    def __init__(self, *args, config_path=None, **kwargs):
        self._config_path = config_path or ['proxy']
        super(ConfigNormerProxy, self).__init__(*args, **kwargs)

    @property
    def config_path(self):
        return self._config_path


    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        proxy_proxy = my_subcfg['proxy']

        ## default proxy values
        proxy_proxy.setdefault('https', proxy_proxy['http'])

        ## create proxy env vars
        proxy_vars = {}

        for k in ['http', 'https']:
            tmp = proxy_proxy.get(k, None)

            if not tmp: continue

            proxy_vars[k + '_proxy'] = tmp

        no_proxy = proxy_proxy.get('noproxy', None)

        if no_proxy:
            proxy_vars['no_proxy'] = ','.join(no_proxy)

        ## some distro's / progs awaits proxy vars to be all caps, 
        ## some to be all lower case, make sure we handle both
        tmp = list(proxy_vars.keys())
        for k in tmp:
            proxy_vars[k.upper()] = proxy_vars[k]

        my_subcfg['vars'] = proxy_vars
        return my_subcfg


