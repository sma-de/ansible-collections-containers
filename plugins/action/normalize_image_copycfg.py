
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import abc
import os

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
        my_subcfg['source_root_suffix'] = os.path.join(
           'to_images', cfg['image_owner'], cfg['image_name']
        )

        return my_subcfg


class ImageCopyCfgNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          CopyFilesNormalizer(pluginref),
        ]

        super(ImageCopyCfgNormalizer, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['copy_cfg']


class CopyFilesNormalizer(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          CopyItemNormalizer(pluginref),
        ]

        super(CopyFilesNormalizer, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['files']


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

