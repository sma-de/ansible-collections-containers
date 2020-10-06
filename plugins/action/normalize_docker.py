
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBase, NormalizerBase, NormalizerNamed
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY

from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR


class DockerConfigNormalizer(NormalizerBase):

    def __init__(self, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageTree(),
        ]

        super(DockerConfigNormalizer, self).__init__(*args, **kwargs)


class DockConfNormImageTree(NormalizerBase):

    def __init__(self, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageOwner(),
        ]

        super(DockConfNormImageTree, self).__init__(*args, **kwargs)

    @property
    def config_path(self):
        return ['images']


class DockConfNormImageOwner(NormalizerBase):

    def __init__(self, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageInstance(),
        ]

        super(DockConfNormImageOwner, self).__init__(*args, **kwargs)

    @property
    def config_path(self):
        return [SUBDICT_METAKEY_ANY]


class DockConfNormImageInstance(NormalizerNamed):

    def __init__(self, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          ConfigNormerProxy(),
        ]

        super(DockConfNormImageInstance, self).__init__(*args, **kwargs)

    @property
    def config_path(self):
        return [SUBDICT_METAKEY_ANY]

    @property
    def name_key(self):
        return 'shortname'

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        owner = cfgpath_abs[-2]
        my_subcfg['owner'] = owner
        my_subcfg['fullname'] = owner + '/' + my_subcfg['shortname']
        return my_subcfg


## docker normalizer
class ActionModule(ConfigNormalizerBase):

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(
            DockerConfigNormalizer(), *args, **kwargs
        )

        self._supports_check_mode = False
        self._supports_async = False


    @property
    def my_ansvar(self):
        return DOCKER_CFG_DEFAULTVAR

    @property
    def merge_args(self):
        tmp = super(ActionModule, self).merge_args

        tmp['invars'] \
          += self.get_taskparam('extra_merge_vars') \
          + ['docker_build_defaults']

        return tmp


    @property
    def argspec(self):
        tmp = super(ActionModule, self).argspec

        tmp.update({
          'extra_merge_vars': {
             'type': [[]],  ## this means type is a list whith no tpe restrictions for list elements
             'defaulting': {
                'ansvar': ['extra_docker_config_maps'],
                'fallback': [],
             },
          }
        })

        return tmp

