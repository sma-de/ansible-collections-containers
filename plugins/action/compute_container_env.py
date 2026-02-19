
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import collections
import json

from ansible.errors import AnsibleOptionsError, AnsibleModuleError##, AnsibleError
####from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems, string_types

from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBase, NormalizerBase, NormalizerNamed
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import \
  get_subdict, \
  SUBDICT_METAKEY_ANY, \
  setdefault_none

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR


class DockInstEnvHandler(NormalizerBase):

    def __init__(self, *args, **kwargs):
        super(DockInstEnvHandler, self).__init__(*args, **kwargs)


    @property
    def config_path(self):
        return ['environment']


    def _handle_modpath(self, modpath, resmap):
        # handle modifying system $PATH for new image
        if not modpath:
            return ## noop

        presents = {
          'front': [],
          'end': [],
          'all': {},
        }

        absents = {}
        keep_presets = False

        def norm_path(px):
            if not isinstance(px, collections.abc.Mapping):
                ## assume simple string
                return px

            if px.get('shell', False):
                ## optionally run given input string as cmd through
                ## shell and use result value as path string
                modret = self.pluginref.exec_module('shell',
                  modargs={'cmd': px['value']}
                )

                px['value'] = modret['stdout']

            return px['value']

        for mp in modpath:
            for p in (mp.get('present', None) or []):
                p = norm_path(p)

                if p in presents['all']:
                    ## dont add something twice
                    continue

                if p in absents:
                    ## dont add paths which are explicitly absented
                    continue

                presents['end'].append(p)
                presents['all'][p] = 'end'

            for p in (mp.get('present_front', None) or []):
                p = norm_path(p)

                if p in presents['front']:
                    ## dont add something twice
                    continue

                if p in absents:
                    ## dont add paths which are explicitly absented
                    continue

                # check if current fronter was previously added as
                # ender, if so remove it there
                x = presents['all'].pop(p, False)
                if x:
                    presets[x].remove(p)

                presents['front'].append(p)
                presents['all'][p] = 'front'

            for a in (mp.get('absent', None) or []):
                a = norm_path(a)
                absents[a] = True

                # check if current absentee was added as presentee
                # earlier, if so remove it there
                x = presents['all'].pop(a, False)
                if x:
                    presets[x].remove(a)

            keep_presets = keep_presets or mp.get('presets', True)

        if not presents['all'] and not absents:
            return  ## noop

        kept_paths = []

        if keep_presets:
            known_paths = {}

            for p in presents['all'].keys():
                known_paths[p] = True

            for p in absents.keys():
                known_paths[p] = False

            for p in resmap['PATH'].split(':'):
                known = known_paths.pop(p, None)

                if known is None or known:
                    # keep paths not explicitly handled, and also
                    # the ones in present obviously
                    kept_paths.append(p)
                ##else: # absentee paths, dont keep them

        ## combine all paths together again in the right order
        new_path = presents['front'] + kept_paths + presents['end']
        resmap['PATH'] = ':'.join(new_path)


    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        handle_dups = self.pluginref.get_taskparam('duplicate_keys')
        force_lists = my_subcfg.get('force_list_mode', None) or {}

        def add_new_envkey(k, v, resmap, keys, handle_dups=handle_dups):
            if k in keys:
                if handle_dups == 'error':
                    raise AnsibleOptionsError(
                      "duplicate environment key '{}'".format(k)
                    )

            if handle_dups == 'list_append' and isinstance(v, list):
                force_x = force_lists.get(k, None) or {}
                force_x_ena = setdefault_none(force_x, 'enabled', True)

                if not isinstance(v, list) and force_x_ena:
                    v = [v]

                if isinstance(v, list):
                    ## if duplicate mode is "list_append" and latest
                    ## value is list, make result list
                    oldval = resmap.get(k, None) or []

                    if not isinstance(oldval, list):
                        oldval = [oldval]

                    oldval += v
                    v = oldval

            resmap[k] = v
            keys.add(k)

        def handle_shellers(shellmap, env_keys, resmap):
            for (k, v) in iteritems(shellmap):
                modret = self.pluginref.exec_module('shell',
                  modargs={'cmd': v}
                )

                add_new_envkey(k, modret['stdout'], resmap, env_keys)

        constenv = get_subdict(my_subcfg, ['static'], default_empty=True)

        ## update: for various reasons we actually get already correct
        ##   updated static vars as extra_envs submap param given,
        ##   which is the reason we kill static from config here
        constenv.clear()

        env_keys = set()

        for xenv in self.pluginref.get_taskparam('extra_envs'):
            for (k, v) in iteritems(xenv):
                add_new_envkey(k, v, constenv, env_keys)

        dynenv = my_subcfg.get('dynamic', {})

        modpath = self.pluginref.get_taskparam('modify_path')

        if modpath:
            modpath = [modpath]
        else:
            modpath = []

        modpath += self.pluginref.get_taskparam('extra_syspath')

        if dynenv or modpath:
            resmap = {}

            tmp = {}

            for (k, v) in iteritems(dynenv.get('expand', {})):
                # use standard env shelling mechanism for expanding env vars
                tmp[k] = 'echo {}'.format(v)

            if modpath:
                # get currently set path on image to build
                tmp['PATH'] = 'echo {}'.format('$PATH')

            if tmp:
                handle_shellers(tmp, env_keys, resmap)

            self._handle_modpath(modpath, resmap)
            shellers = dynenv.get('shell', {})

            if shellers:
                handle_shellers(shellers, env_keys, resmap)

            from_av = dynenv.get('from_autover', {})

            if from_av:
                av = self.pluginref.get_taskparam('auto_version')

                for k, v in from_av.items():
                    av_val = av

                    for x in v.split('.'):
                        if x not in av_val:
                            raise AnsibleOptionsError(
                                "invalid auto_version key '{}', partial"\
                                " subkey '{}' is not valid:\n  {}".format(
                                    v, x, json.dumps(av_val, indent=2).replace(
                                       '\n', '\n  '
                                    )
                                )
                            )

                        av_val = av_val[x]
                    add_new_envkey(k, av_val, resmap, env_keys)

            constenv.update(resmap)

        ## finalize / norm env vars
        for k in list(constenv.keys()):
            v = constenv[k]

            if isinstance(v, list):
                ## make list values strings
                v = ' '.join(v)

            constenv[k] = v

        ## handle some generic special cases

        ## check if we have java installations on system, if so
        ## and JAVA_HOME is not set, default it to active jvm
        java = self.pluginref.get_ansible_fact('java', default=None)

        if java:
            setdefault_none(constenv, 'JAVA_HOME', java['active']['homedir'])

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
          'extra_syspath': ([[collections.abc.Mapping]], []),
          'duplicate_keys': (list(string_types), 'error',
             ['overwrite', 'error', 'list_append']
          ),
          'auto_version': ([collections.abc.Mapping], {}),
        })

        return tmp

