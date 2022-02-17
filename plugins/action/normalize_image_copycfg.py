
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import abc
import pathlib

from ansible.errors import AnsibleOptionsError
from ansible.module_utils.six import iteritems, string_types

from ansible_collections.smabot.base.plugins.action.normalize_rectemplate_cfg import CopyItemNormalizer
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import ConfigNormalizerBase, NormalizerBase, NormalizerNamed
from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert



class ConfigRootNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          ImageCopyCfgNormalizer(pluginref),
        ]

        super(ConfigRootNormalizer, self).__init__(pluginref, *args, **kwargs)


    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        img_cfg = my_subcfg['image_config']

        tmp = pathlib.PurePosixPath(img_cfg['role_dir']) / '{}' \
            / 'to_images' / img_cfg['owner'] / img_cfg['shortname']

        tmp = str(tmp)

        my_subcfg['source_root'] = tmp.format('files')
        my_subcfg['_source_root_templates'] = tmp.format('templates')

        my_subcfg['image_id'] = img_cfg['owner'] + '/' + img_cfg['shortname']
        return my_subcfg


class ImageCopyCfgNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          CopyFilesNormalizer(pluginref),
          CopyTemplatesNormalizer(pluginref),
        ]

        super(ImageCopyCfgNormalizer, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['copy_cfg']



class CopyFilesNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockerCopyItemNormer(pluginref),
        ]

        super(CopyFilesNormalizer, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['files']



class CopyTemplatesNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockerCopyItemNormer(pluginref),
        ]

        super(CopyTemplatesNormalizer, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['templates']



class DockerCopyItemNormerBase():

    def magic_owner_docker_user(self, cfg, my_subcfg, cfgpath_abs):
        pcfg = self.get_parentcfg(cfg, cfgpath_abs, level=3)
        return pcfg['image_config']['docker_user']


    MAGIC_OWNER_MAP = {
      '<DOCKER_USER>': magic_owner_docker_user,
    }


    def _handle_specifics_postsub(self, cfg, my_subcfg, cfgpath_abs):
        capi = my_subcfg['copy_api']

        # handle magic owners
        tmp = capi.get('owner', '')
        tmp = self.MAGIC_OWNER_MAP.get(tmp, None)

        if tmp:
            capi['owner'] = tmp(self, cfg, my_subcfg, cfgpath_abs)

        return super()._handle_specifics_postsub(cfg, my_subcfg, cfgpath_abs)



class DockerCopyItemNormer(DockerCopyItemNormerBase, CopyItemNormalizer):
    pass



class ActionModule(ConfigNormalizerBase):

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(
            ConfigRootNormalizer(self), *args, **kwargs
        )

        self._supports_check_mode = False
        self._supports_async = False


    @property
    def my_ansvar(self):
        return 'copy_to_image_args'

    @property
    def supports_merging(self):
        return False

