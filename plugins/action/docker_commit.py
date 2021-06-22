
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import collections
import json
import re

##from ansible.errors import AnsibleOptionsError, AnsibleModuleError##, AnsibleError
####from ansible.module_utils._text import to_native
from ansible.module_utils.six import iteritems, string_types

from ansible_collections.smabot.base.plugins.module_utils.plugins.action_base import BaseAction

##from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import get_subdict, SUBDICT_METAKEY_ANY
##from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert
##from ansible_collections.smabot.containers.plugins.module_utils.common import DOCKER_CFG_DEFAULTVAR


class ActionModule(BaseAction):

    def __init__(self, *args, **kwargs):
        super(ActionModule, self).__init__(*args, **kwargs)
        self._supports_check_mode = False
        self._supports_async = False


    @property
    def argspec(self):
        tmp = super(ActionModule, self).argspec

        dkeys_subspec = {
          'CMD': (list(string_types) + [list(string_types)], []),
          'ENTRYPOINT': (list(string_types) + [list(string_types)], []),
          'ENV': ([collections.abc.Mapping], {}),
          'EXPOSE': ([list(string_types)], []),
          'LABEL': ([list(string_types)], []),
          'USER': (list(string_types), ''),
          'WORKDIR': (list(string_types), ''),
        }

        tmp.update({
          'container': (list(string_types)),
          'image_name': (list(string_types)),
          'image_tag': (list(string_types), ''),
          'force': ([bool], False),

          'docker_keywords': ([collections.abc.Mapping], {}, dkeys_subspec),
        })

        return tmp


    def run_specific(self, result):
        imgname = self.get_taskparam('image_name')
        imgtag = self.get_taskparam('image_tag')
        force = self.get_taskparam('force')

        img_fullname = imgname

        if imgtag:
            img_fullname += ':' + imgtag

        ## image exists means for us something with given name 
        ## already exists on docker build node or is pullable
        pullmod = 'community.docker.docker_image'
        mres = self.exec_module(pullmod, 
          modargs=dict(name=img_fullname, source='pull'), ignore_error=True
        )

        ## image already exists on node => pull modules returns green
        ## image is pullable => pull modules returns yellow
        ## image does not exist yet => pull modules fails
        img_exists = True

        if mres.get('failed', False):
            ## check if it failed simply because image does not 
            ## exist yet or if something is actually really wrong

            if not re.search(r'(?i)404 client error.*?: not found', mres['msg']):
                self._rescheck_inner_call(mres, pullmod, 'MODULE')

            img_exists = False

        if img_exists and not force:
            ## image already exists and force is unset, noop
            result['msg'] = \
               "Image with given name '{}' already exists, will not"\
               " change it unless force is set to true".format(img_fullname)

            return result

        ##
        ## note: we only do basic name checking, no advanced testing 
        ##   if existing image and container to commit are identical 
        ##   or not based on content, so like updating a password or 
        ##   doing a git commit, if we come here, this is an ever changer
        ##
        ## TODO: there is not really a feasible way to determine if the container to commit and a possible pre-existing image with the same name are idempotent or not, or is there ??
        ##
        result['changed'] = True

        container = self.get_taskparam('container')

        ## build commit command
        commit_command = ['docker', 'commit']

        ## handle docker keywords
        json_keys = ['CMD', 'ENTRYPOINT']
        for (k, v) in iteritems(self.get_taskparam('docker_keywords')):
            if not v: continue

            if isinstance(v, collections.abc.Mapping):
                tmp = []

                for (vk, vv) in iteritems(v):
                    tmp.append("{}={}".format(vk, vv))

                v = tmp
            elif isinstance(v, list):
                if k in json_keys:
                    v = [json.dumps(v)]
            else:
                v = [v]

            for x in v:
                x = "{} {}".format(k, x)
                commit_command += ['-c', x]

        commit_command += [container, img_fullname]

        mres = self.exec_module('command', modargs={'argv': commit_command})

        return result

