
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBaseMerger, NormalizerBase, NormalizerNamed, DefaultSetterConstant
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY, setdefault_none

from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible.utils.display import Display


display = Display()


def get_docker_parent_infos(pluginref, parent_name):
    tmp = pluginref.exec_module('community.general.docker_image_info', 
       modargs={'name': parent_name}
    )

    errmsg = "Bad docker parent info query for parent"\
             " name '{}'.".format(parent_name) + "{}."\
           + "Raw result: " + str(tmp)

    t2 = tmp.get('images', None)

    ansible_assert(t2, errmsg.format("No Images returned"))
    ansible_assert(len(t2) == 1, errmsg.format(
      "Expected exactly one image returned, but got '{}'".format(len(t2))
    ))

    tmp = t2[0]

    return tmp


class DockerConfigNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageTree(pluginref),
        ]

        super(DockerConfigNormalizer, self).__init__(pluginref, *args, **kwargs)


class DockConfNormImageTree(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageOwner(pluginref),
        ]

        super(DockConfNormImageTree, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['images']


class DockConfNormImageOwner(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageInstance(pluginref),
        ]

        super(DockConfNormImageOwner, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return [SUBDICT_METAKEY_ANY]


class DockConfNormImageInstance(NormalizerNamed):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          ConfigNormerProxy(pluginref),
          DockConfNormImageUsersGeneric(pluginref),
        ]

        super(DockConfNormImageInstance, self).__init__(pluginref, *args, **kwargs)

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

    def _handle_specifics_postsub(self, cfg, my_subcfg, cfgpath_abs):
        du = my_subcfg.get('docker_user', None)

        if not du:
            # default docker user to parent image user (or config 
            # defined fallback user) if it exists
            du = my_subcfg['users'].get('docker_default_user', '')
            my_subcfg['docker_user'] = du

        return my_subcfg


class DockConfNormImageUsersGeneric(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'users', DefaultSetterConstant(dict())
        )

        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageUsersList(pluginref),
        ]

        super(DockConfNormImageUsersGeneric, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['users']

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        # query upstream image metadata
        pinfs = get_docker_parent_infos(self.pluginref, 
          self.get_parentcfg(cfg, cfgpath_abs)['parent']
        )

        dpu = pinfs['Config']['User']

        ddu = my_subcfg.get('docker_default_user', None) or {}
        dfu = my_subcfg.get('docker_fallback_user', None) or {}

        if dpu:
            # if upstream / parent image has a user set, use that 
            # as docker default user
            pass
        elif dfu:
            # if no upstream default user is set but config specified 
            # a fallback user config, use that as docker default user
            ddu.update(dfu)
            dpu = dfu['config']['name']

        if dpu:
            # if we have a docker default user make sure it is added 
            # to users list
            my_subcfg['docker_default_user'] = dpu
            my_subcfg['users'][dpu] = ddu

        return my_subcfg


class DockConfNormImageUsersList(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageUser(pluginref),
        ]

        super(DockConfNormImageUsersList, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['users']


class DockConfNormImageUser(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'config', DefaultSetterConstant(dict())
        )

        super(DockConfNormImageUser, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return [SUBDICT_METAKEY_ANY]

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        cfg = my_subcfg['config']
        setdefault_none(cfg, 'name', cfgpath_abs[-1])
        return my_subcfg


## docker normalizer
class ActionModule(ConfigNormalizerBaseMerger):

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(DockerConfigNormalizer(self), 
            *args, default_merge_vars=['docker_build_defaults_role', 'docker_build_defaults'], 
            extra_merge_vars_ans=['extra_docker_config_maps'], **kwargs
        )

        self._supports_check_mode = False
        self._supports_async = False


    @property
    def my_ansvar(self):
        return DOCKER_CFG_DEFAULTVAR

