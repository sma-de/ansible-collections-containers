
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import abc
import copy
import os 
import re

from ansible.errors import AnsibleOptionsError

from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.base import \
  ConfigNormalizerBaseMerger, \
  NormalizerBase, \
  NormalizerNamed, \
  DefaultSetterConstant, \
  SIMPLEKEY_IGNORE_VAL

from ansible_collections.smabot.base.plugins.module_utils.plugins.config_normalizing.proxy import ConfigNormerProxy
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import \
  get_subdict, \
  merge_dicts, \
  setdefault_none, \
  SUBDICT_METAKEY_ANY

from ansible_collections.smabot.containers.plugins.module_utils.common import \
  add_deco, \
  DOCKER_CFG_DEFAULTVAR

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible.utils.display import Display


display = Display()


class ScmHandler(abc.ABC):

    def __init__(self, pluginref):
        self.pluginref = pluginref

    @abc.abstractmethod
    def get_current_commit_hash(self, repo_path):
        pass

    @abc.abstractmethod
    def get_current_commit_authorname(self, repo_path):
        pass

    @abc.abstractmethod
    def get_current_commit_authormail(self, repo_path):
        pass

    @abc.abstractmethod
    def get_current_commit_timestamp(self, repo_path):
        pass


class ScmHandlerGit(ScmHandler):

    def _standard_gitcmd(self, repo_path, *cmd):
        res = self.pluginref.exec_module('ansible.builtin.command', 
          modargs={'argv': ['git'] + list(cmd), 'chdir': repo_path}
        ) 

        return res['stdout'].strip()

    def _logformat_cmd(self, repo_path, formstr):
        return self._standard_gitcmd(repo_path, 
          'log', '-1', "--pretty=format:%{}".format(formstr)
        )

    def get_current_commit_hash(self, repo_path):
        return self._standard_gitcmd(repo_path, 'rev-parse', 'HEAD')

    def get_current_commit_authorname(self, repo_path):
        return self._logformat_cmd(repo_path, 'an')

    def get_current_commit_authormail(self, repo_path):
        return self._logformat_cmd(repo_path, 'ae')

    def get_current_commit_timestamp(self, repo_path):
        return self._logformat_cmd(repo_path, 'cd')

    def get_current_commit_branch_heads(self, repo_path):
        curhash = self.get_current_commit_hash(repo_path)

        local_branches = []
        remote_branches = []

        tmp = self._standard_gitcmd(repo_path, 'show-ref')

        for l in tmp.split('\n'):
            h, ref = re.split(r'\s+', l)

            if h != curhash:
                continue

            p = 'refs/heads/'

            if ref.startswith(p):
                local_branches.append(ref[len(p):])

            p = 'refs/remotes/'

            if ref.startswith(p):
                remote_branches.append(ref[len(p):])

        return {
          'local': local_branches,
          'remote': remote_branches,
        }



def mod_branch_norming(branch, replacements=None):
    for r in replacements:
        old, new = r
        branch = re.sub(old, new, branch)

    return branch


def mod_branch_prefix_remove(branch, prefix_list=None):
    for pfx in prefix_list:
        if branch.startswith(pfx):
            branch = branch[len(pfx):]

    return branch


def mod_branch(branch, modcfg):
    if not modcfg:
        return branch

    for m in modcfg:
        mid = m['id']
        mfn = globals().get('mod_branch_' + mid, None)

        if not mfn:
            raise AnsibleOptionsError(
              "Unsupported branch mod function '{}'".format(mid)
            )

        branch = mfn(branch, **m['params'])

    return branch


def get_type_handler(scmtype, *args):
    # TODO: support other scm
    if scmtype == 'git':
        return ScmHandlerGit(*args)

    raise AnsibleOptionsError("Unsupported scm type '{}'".format(scmtype))


def get_docker_parent_infos(pluginref, parent_name):
    ## note: docker_image_info will never pull an image and only 
    ##   examines local images, so we need this extra explicit pull before 
    pluginref.exec_module('community.docker.docker_image', 
      modargs={'name': parent_name, 'source': 'pull', 'force_source': True}
    )

    tmp = pluginref.exec_module('community.docker.docker_image_info', 
       modargs={'name': parent_name}
    )

    errmsg = "Bad docker parent info query for parent"\
             " name '{}'.".format(parent_name) + " {}."\
           + " Raw result: " + str(tmp).replace('{', '{{').replace('}', '}}')

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
          DockConfNormMeta(pluginref),
          DockConfNormImageTree(pluginref),
        ]

        super(DockerConfigNormalizer, self).__init__(pluginref, *args, **kwargs)


class DockConfNormMeta(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'create', DefaultSetterConstant(False)
        )

        self._add_defaultsetter(kwargs, 
          'exports', DefaultSetterConstant({})
        )

        super(DockConfNormMeta, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['meta']


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
        self._add_defaultsetter(kwargs, 
          'tags', DefaultSetterConstant([])
        )

        self._add_defaultsetter(kwargs, 
          'environment', DefaultSetterConstant(dict())
        )

        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          ##
          ## note: on default proxy eco-systems (like java) are on 
          ##   auto-detect mode, which means they only are handled 
          ##   when eco-system is detected on target, but as our 
          ##   target here is the container we will build but this 
          ##   normalizing is (has to be) done before we switch 
          ##   into container index we will force eco system 
          ##   handling "on" here and will decide later if we use 
          ##   them actually (note: this implies that we never 
          ##   actually must interact with the ecosystem in question 
          ##   for doing proper proxy normalizing for it)
          ##
          ConfigNormerProxy(pluginref, force_ecosystems=True),
          (DockConfNormImageSCMBased, True), # make this lazy initialized (only set it, when it already exists in input cfg)
          (DockConfNormImageAutoVersioning, True), # make this lazy initialized
          DockConfNormImageUsersGeneric(pluginref),
          DockConfNormImageDecorations(pluginref),
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
        ## handle docker user defaulting
        du = my_subcfg.get('docker_user', None)

        if not du:
            # default docker user to parent image user (or config 
            # defined fallback user) if it exists
            du = my_subcfg['users'].get('docker_default_user', '')
            my_subcfg['docker_user'] = du

        ## handle authors defaulting
        authors = my_subcfg.get('authors', None)

        if not authors:
            scm_based = my_subcfg.get('scm_based', None)

            if scm_based:
                ## when we are scm based, default image author to commit author
                an = scm_based['metadata']['curcommit_authorname']
                ae = scm_based['metadata']['curcommit_authormail']

                if ae:
                    an += ' <{}>'.format(ae)

                authors = [an]

        if authors:
            my_subcfg['authors'] = authors

            ## decorate container image with author info
            authors = ', '.join(authors)
            add_deco(my_subcfg['decorations'], 
               'contimg_authors', authors, 
               add_env=['CONTIMG_AUTHORS'], 

               #
               # note: prefer to use "official" OCI standard label 
               #   keys when avaible: 
               #     https://github.com/opencontainers/image-spec/blob/main/annotations.md
               #
               add_label=['org.opencontainers.image.authors'], 
               only_when_empty=True
            )

        ## optionally append extra tags from env
        tmp = os.environ.get('SMABOT_CONTAINERS_BLDR_EXTRA_IMGTAGS', None)

        if tmp:
            my_subcfg['tags'] += re.split(r'\s+', tmp.strip())

        return my_subcfg


class DockConfNormImageSCMBased(NormalizerBase):

    NORMER_CONFIG_PATH = ['scm_based']

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'metadata', DefaultSetterConstant(dict())
        )

        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageSCMBasedConfig(pluginref),
        ]

        super(DockConfNormImageSCMBased, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return self.NORMER_CONFIG_PATH

    @property
    def simpleform_key(self):
        return SIMPLEKEY_IGNORE_VAL

    def _handle_specifics_postsub(self, cfg, my_subcfg, cfgpath_abs):
        # default fill scm metadata
        repo_path = my_subcfg['config']['repo_path']
        tmp = get_type_handler(my_subcfg['config']['type'], self.pluginref)
        md = my_subcfg['metadata']

        setdefault_none(md, 'curcommit_hash', 
          tmp.get_current_commit_hash(repo_path)
        )

        setdefault_none(md, 'curcommit_authorname', 
          tmp.get_current_commit_authorname(repo_path)
        )

        setdefault_none(md, 'curcommit_authormail', 
          tmp.get_current_commit_authormail(repo_path)
        )

        setdefault_none(md, 'curcommit_timestamp', 
          tmp.get_current_commit_timestamp(repo_path)
        )

        branches = setdefault_none(md, 'curcommit_branch_heads', 
          tmp.get_current_commit_branch_heads(repo_path)
        )

        pcfg = self.get_parentcfg(cfg, cfgpath_abs)

        # optionally create branch tags
        bt_cfg = my_subcfg['config'].get('branch_tags', None)

        if bt_cfg and branches:
            tags = pcfg['tags']

            tmp = []

            if bt_cfg['local']:
                tmp += branches.get('local', [])

            if bt_cfg['remote']:
                tmp += branches.get('remote', [])

            btmods = bt_cfg['mods']

            for b in tmp:
                tags.append(bt_cfg['prefix'] + mod_branch(b, btmods))

        return my_subcfg


class DockConfNormImageSCMBasedConfig(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'type', DefaultSetterConstant('git')
        )

        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          (DockConfNormImageSCMBasedCfgBranchTags, True),
        ]

        super(DockConfNormImageSCMBasedConfig, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['config']

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        # on default assume that the playbook_dir is the best bet 
        # for the correct repo path
        setdefault_none(my_subcfg, 'repo_path', 
          self.pluginref.get_ansible_var('playbook_dir')
        )

        return my_subcfg


class DockConfNormImageSCMBasedCfgBranchTags(NormalizerBase):

    NORMER_CONFIG_PATH = ['branch_tags']

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'local', DefaultSetterConstant(False)
        )

        self._add_defaultsetter(kwargs, 
          'remote', DefaultSetterConstant(True)
        )

        self._add_defaultsetter(kwargs, 
          'prefix', DefaultSetterConstant('bt_')
        )

        self._add_defaultsetter(kwargs, 
          'mods', DefaultSetterConstant([])
        )

        super(DockConfNormImageSCMBasedCfgBranchTags, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return self.NORMER_CONFIG_PATH

    @property
    def simpleform_key(self):
        return SIMPLEKEY_IGNORE_VAL

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        mods = my_subcfg['mods']

        if not mods:
            mods.append({
              'id': 'prefix_remove', 
              'params': { 'prefix_list': ['origin/'] },
            })

        # if no user explicit norming is defined, set standard norming 
        # fn as there are simply a lot of common symbols which are 
        # not allowed in tags (like e.g. slashes)
        normcfg = None

        for m in mods:
            if m['id'] == 'norming':
                normcfg = m
                break

        if not normcfg:
            mods.append({
              'id': 'norming', 
              'params': { 'replacements': [['/', '_'], [':', '_']] },
            })

        return my_subcfg


class DockConfNormImageDecorations(NormalizerBase):

    def __init__(self, pluginref, *args, **kwargs):
        self._add_defaultsetter(kwargs, 
          'deco', DefaultSetterConstant(dict())
        )

        super(DockConfNormImageDecorations, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return ['decorations']

    @property
    def simpleform_key(self):
        return SIMPLEKEY_IGNORE_VAL

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        pcfg = self.get_parentcfg(cfg, cfgpath_abs)
        tmp = pcfg.get('scm_based', None)

        #deco = my_subcfg['deco']

        if tmp:
            scm_meta = copy.deepcopy(tmp)
            scm_preset_meta = scm_meta.pop('metadata', {})

            merge_dicts(scm_meta, my_subcfg.get('scm_meta', {}))
            my_subcfg['scm_meta'] = scm_meta

            chash = scm_preset_meta.get('curcommit_hash', None)

            if chash:
                # optionally default decorate with scm hash
                add_deco(my_subcfg, 'contimg_scmhash', chash, 
                   add_env=['CONTIMG_SCMHASH'], 
                   add_label=['org.opencontainers.image.revision'], 
                   only_when_empty=True
                )

            cts = scm_preset_meta.get('curcommit_timestamp', None)

            if cts:
                # optionally default decorate with scm timestamp
                add_deco(my_subcfg, 'contimg_scmts', cts, 
                   add_env=['CONTIMG_SCMTS'], 
                   add_label=['contimage.self.scm_timestamp'], 
                   only_when_empty=True
                )

        return my_subcfg


class DockConfNormImageAutoVersioning(NormalizerBase):

    NORMER_CONFIG_PATH = ['auto_versioning']

    def __init__(self, pluginref, *args, **kwargs):
        subnorms = kwargs.setdefault('sub_normalizers', [])
        subnorms += [
          DockConfNormImageAutoVerSCMBased(pluginref),
        ]

        super(DockConfNormImageAutoVersioning, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return self.NORMER_CONFIG_PATH


class DockConfNormImageAutoVerSCMBased(NormalizerBase):

    NORMER_CONFIG_PATH = ['scm_based']

    def __init__(self, pluginref, *args, **kwargs):
        super(DockConfNormImageAutoVerSCMBased, self).__init__(pluginref, *args, **kwargs)

    @property
    def config_path(self):
        return self.NORMER_CONFIG_PATH

    @property
    def simpleform_key(self):
        return SIMPLEKEY_IGNORE_VAL

    def _handle_specifics_presub(self, cfg, my_subcfg, cfgpath_abs):
        tmp = self.get_parentcfg(cfg, cfgpath_abs, 2)
        tmp = tmp.get('scm_based', None)

        if not tmp:
            return my_subcfg

        scmcfg = copy.deepcopy(tmp['config'])
        merge_dicts(scmcfg, my_subcfg)
        my_subcfg.update(scmcfg)

        setdefault_none(my_subcfg, 'date_format', '%Y%m%d_%H%m')

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

