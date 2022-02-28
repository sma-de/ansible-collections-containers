

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'community'
}

import collections
import copy
import re
import os

from ansible.errors import AnsibleFilterError, AnsibleOptionsError
from ansible.module_utils.six import string_types
from ansible.module_utils.common._collections_compat import MutableMapping
from ansible.module_utils._text import to_text, to_native

from ansible_collections.smabot.base.plugins.module_utils.plugins.plugin_base import MAGIC_ARGSPECKEY_META
from ansible_collections.smabot.base.plugins.module_utils.plugins.filter_base import FilterBase

from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import merge_dicts, setdefault_none
from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert

from ansible_collections.smabot.containers.plugins.module_utils.common import add_deco

from ansible.utils.display import Display


display = Display()



class AutoVersionPostProc(FilterBase):

    FILTER_ID = 'autover_postproc'

    @property
    def argspec(self):
        tmp = super(AutoVersionPostProc, self).argspec

        cgrp_spec = {
          'regex': (list(string_types), ''),
          'version': (list(string_types), ''),
        }

        tmp.update({
          'capture_group': ([collections.abc.Mapping], {}, cgrp_spec),
        })

        return tmp


    def run_specific(self, value):
        if not isinstance(value, string_types):
            raise AnsibleOptionsError("expects a string as filter input")

        cgrp = self.get_taskparam('capture_group')
        cgrp_re = cgrp['regex']
        cgrp_ver = cgrp['version']

        if cgrp_re:
            # do capture_group post processing: regex search input
            # string for capture_group and extract matched version
            # (sub) string from it

            tmp = cgrp_re.format(VERSION=r'(?P<version>{})'.format(cgrp_ver))

            errpfx = \
               "capture group must match exactly once, but for"\
               " given parameters regex => '{}' and version => '{}'"\
               " combined into the following final regex pattern"\
               " => '{}'".format(cgrp_re, cgrp_ver, tmp)

            found_match = None
            for m in re.finditer(tmp, value, flags=re.MULTILINE):
                if found_match:
                    raise AnsibleOptionsError(errpxf + " more than one match was found")

                found_match = m.group('version')

            if not found_match:
                raise AnsibleOptionsError(errpxf + " no match was found")

            value = found_match

        return value



class CombineBuildMetaFilter(FilterBase):

    FILTER_ID = 'combine_buildmeta'

    @property
    def argspec(self):
        tmp = super(CombineBuildMetaFilter, self).argspec

        tmp.update({
          'metacfg': ([collections.abc.Mapping]),
          'imgcfg': ([collections.abc.Mapping]),
          'ansible_facts': ([collections.abc.Mapping]),
          'auto_versioning': ([collections.abc.Mapping], {}),
        })

        return tmp


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        metacfg = self.get_taskparam('metacfg')
        imgcfg = self.get_taskparam('imgcfg')

        ## add select container facts to build meta
        fact_keys = metacfg['facts']

        if fact_keys:
            ans_facts = self.get_taskparam('ansible_facts')
            facts = {}

            for k in fact_keys:
                ## expect all keys to exist, otherwise error out
                facts[k] = ans_facts[k]

            value['facts'] = facts

        ## add auto versioning settings to build meta
        autov = self.get_taskparam('auto_versioning')
        
        if autov:
            ## check if a package install is auto versionend, 
            ##   if so add package info to meta
            package = imgcfg['packages'].get('auto_versioned', None)

            if package:
                autov['package'] = package

            value['auto_versioning'] = autov

        return value



class PSetsFilter(FilterBase):

    FILTER_ID = 'to_psets'

    @property
    def argspec(self):
        tmp = super(PSetsFilter, self).argspec

        tmp.update({
          'os_family': (list(string_types), ''),
          'os_defaults': ([collections.abc.Mapping], {}),
          'extra_packages': ([collections.abc.Mapping], {}),
          'auto_version': ([collections.abc.Mapping], {}),
          'grouped': ([bool], True),
          'pkg_convfn': (list(string_types), '', ['', 'maven']),
        })

        return tmp


    def _package_conv_maven(self, package,
        defaults=None, grouped=False, base_map=None
    ):
        tmp = copy.deepcopy(defaults)
        merge_dicts(tmp, copy.deepcopy(package))

        # fill in sources key list with sources info dicts
        p_sources = []
        for sk in tmp['sources']:
            if not isinstance(sk, collections.abc.Mapping):
                sk = base_map['sources'][sk]

            p_sources.append(sk)

        tmp['sources'] = p_sources

        # note: atm simply hardcode first source
        # TODO: support multiple sources trying one after another if first one fails
        active_src = p_sources[0]

        # apply source defaults to this package
        tmp = merge_dicts(
          copy.deepcopy(active_src.get('defaults', {})), tmp
        )

        # this dict is passed 1:1 to maven ansible module
        pcfg = setdefault_none(tmp, 'config', {})

        pcfg['state'] = tmp['state']
        pcfg['repository_url'] = active_src['url']

        # handle maven download part
        mvn_coords = tmp['coordinates']

        pcfg['artifact_id'] = mvn_coords['aid']
        pcfg[    'version'] = tmp.get('version', None)
        pcfg[  'extension'] = mvn_coords.get('type', None)

        gid = mvn_coords.get('gid', None)

        if gid:
            if isinstance(gid, list):
                gid = '.'.join(gid)

            pcfg['group_id'] = gid

        clss = mvn_coords.get('class', None)

        if clss:
            if isinstance(clss, list):
                clss = tmp['class_joiner'].join(clss)

            pcfg['classifier'] = clss

        # handle remote system destination part
        pdst = tmp['destination']
        dest_path = pdst['path']

        merge_dicts(pcfg, pdst.get('config', {}))

        if pdst['singlefile']:
            pcfg['dest'] = os.path.dirname(dest_path)
        else:
            pcfg['dest'] = dest_path

        unpack_cfg = setdefault_none(pdst, 'unpacking', False)

        if unpack_cfg:
            if not isinstance(unpack_cfg, collections.abc.Mapping):
                unpack_cfg = {}
                pdst['unpacking'] = unpack_cfg

            csums = setdefault_none(unpack_cfg, 'checksums', {})
            for k in csums:
                v = csums[k]

                if not isinstance(v, collections.abc.Mapping):
                    v = { 'sum': v }

                if not pdst['singlefile']:
                    cs_file = v.get('file', None)
                    ansible_assert(cs_file,
                       "For checking checksums after unpacking a"\
                       " reference filename must be provided when"\
                       " destination path is a directory instead"\
                       " of a complete filepath: {}".format(tmp['name'])
                    )

                    v['file'] = os.path.join(dest_path, cs_file)

                csums[k] = v

        return tmp


    def _get_matching_pset(self, package, psets, default_settings):
        ## get package level module option overwrites
        p_modopts = package.get('modopts', None)

        if not p_modopts:
            # if package has no module option overwrites, 
            # just use the default first one
            return psets[0]

        for ps in psets:
            matches = True

            for (k, v) in p_modopts.items():
                if k not in ps:
                    # for pset purposes, a non set key counts as mismatch
                    matches = False
                    break

                if ps[k] != v:
                    # pset mod opt value differs from package overwrite 
                    # value, so no match
                    matches = False
                    break

            if matches:
                return ps

        # no existing pset matches specific package overwrites, 
        # so create a new one
        tmp = copy.deepcopy(default_settings)
        tmp.update(p_modopts)
        psets.append(tmp)

        return tmp


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        packages = copy.deepcopy(value['packages'])
        pconv_fn = self.get_taskparam('pkg_convfn')

        tmp = self.get_taskparam('extra_packages')
        if tmp:
            if not isinstance(tmp, list):
                tmp = [tmp]

            packages = tmp + packages

        psets = []
        ungrouped_psets = []

        if not packages:
            # no packages configured, so psets are empty
            return psets

        os_family = self.get_taskparam('os_family')
        autov_setting = self.get_taskparam('auto_version')
        defaults = copy.deepcopy(self.get_taskparam('os_defaults'))
        merge_dicts(defaults, copy.deepcopy(value['default_settings']))

        # many package manager modules suppport handling multiple packages 
        # at once (list), but some dont, which we will handle by making 
        # each package basically its own pset
        grouped = self.get_taskparam('grouped')

        meta_defaults = {}

        for x in ['version_comparator']:
            meta_defaults[x] = defaults.pop(x, None)

        for ps in packages:
            sub_psets = []

            ps_defaults = copy.deepcopy(defaults)
            tmp = ps.pop('_set_defaults_', None)

            if tmp:
                merge_dicts(ps_defaults, tmp)

            sub_psets.append(ps_defaults)

            for (k, v) in ps.items():
                v = v or {}
                v.setdefault('name', k)

                if os_family:
                    # check for os specific overwrite keys
                    os_overwrites = v.get('os_overwrites', {}).get(
                      os_family.lower(), None
                    )

                    if os_overwrites:
                        merge_dicts(v, os_overwrites)

                # handle packages marked as auto versioned
                is_autov = v.get('auto_versioned', False)
                if is_autov:
                    tmp = autov_setting.get('version_in', None)

                    if not tmp:
                        raise AnsibleOptionsError(
                           "Package to install with name '{}' had auto"\
                           " versioning flag set, but no auto version"\
                           " was determined".format(v['name'])
                        )

                    v['version'] = tmp

                # run type specific package conv fn
                if pconv_fn:
                    assert not grouped
                    ungrouped_psets.append(
                      getattr(self, '_package_conv_' + pconv_fn)(
                        v, defaults=defaults, grouped=grouped, base_map=value
                      )
                    )

                else:
                    # find the correct pset for package
                    tmp = self._get_matching_pset(v, sub_psets, defaults)

                    # handle packages which are explicitly pinned to some version
                    pver = v.get('version', None)
                    if grouped:
                        n = v['name']

                        # add package to pset
                        if pver:
                            vercompare = v.get('version_comparator', 
                               meta_defaults['version_comparator'] or "="
                            )

                            if grouped:
                                n = "{}{}{}".format(v['name'], vercompare, pver)

                        tmp.setdefault('name', []).append(n)
                    else:
                        tmp = copy.deepcopy(tmp)
                        tmp['name'] = v['name']

                        if pver:
                            tmp['version'] = pver

                        ungrouped_psets.append(tmp)

            # finally make a flat list of all config defined psets 
            # and sub_psets created by this method, but keep the 
            # original config pset order and also dont mix 
            # different sub_psets together
            psets += sub_psets

        if not grouped:
            psets = ungrouped_psets

        return psets



class AppendContEnvFilter(FilterBase):

    FILTER_ID = 'append_contenv'

    @property
    def argspec(self):
        tmp = super(AppendContEnvFilter, self).argspec

        tmp.update({
          'new_vars': ([collections.abc.Mapping],),
          'strategy': (list(string_types), 'replace'),
          'stratopts': ([collections.abc.Mapping], {}),
        })

        return tmp


    def _do_strat_basic(self, conflict_handler, key, curvars, newvars, **kwargs):
        if key not in curvars:
            # if key is also new, we dont have a conflict
            return newvars[key]

        oldval = curvars[key]
        newval = newvars[key]

        return conflict_handler(key, oldval, newval, **kwargs)


    def do_strat_write_once(self, key, oldval, newval, **kwargs):
        if oldval == newval:
            # if for some strange reason oldval and newval 
            # are identical, there is no reason to error out I guess
            return oldval

        ## write once does not allow resetting existing keys, 
        ## so it simply generates an error when a write conflict occours
        raise AnsibleFilterError(
           "Trying to overwrite already existing var key '{}' with"\
           " current value '{}' with value '{}', but selected"\
           " write_once strategy forbids resetting keys.".format(
              k, oldval, newval
           )
        )


    def do_strat_keep_first(self, key, oldval, newval, **kwargs):
        ## keep first strat prefers old over new value
        return oldval


    def do_strat_replace(self, key, oldval, newval, **kwargs):
        ## replace strat always prefers newval over oldval
        return newval


    def do_strat_combine(self, key, oldval, newval, 
        old_first=True, combiner=' ', **kwargs
    ):
        ## combine strat combines old and new value
        if old_first:
            return oldval + combiner + newval
        return newval + combiner + oldval


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        curvars = value.setdefault('vars', {})
        newvars = self.get_taskparam('new_vars')

        strat = self.get_taskparam('strategy')
        stratopts = self.get_taskparam('stratopts')

        tmp = getattr(self, 'do_strat_' + strat, None)

        if not tmp:
            raise AnsibleOptionsError(
               "Unsupported strategy '{}'".format(strat)
            )

        strat = tmp

        for (k, v) in newvars.items():
            curvars[k] = self._do_strat_basic(
              strat, k, curvars, newvars, **stratopts
            )

        return value


class DecoAddFilter(FilterBase):

    FILTER_ID = 'add_deco'

##    def __init__(self, *args, **kwargs):
##        super(FilterBase, self).__init__(*args, **kwargs)

    @property
    def argspec(self):
        tmp = super(DecoAddFilter, self).argspec

        tmp.update({
          'key': (list(string_types),),
          'value': (list(string_types),),
          'add_env': ([list(string_types)], []),
          'add_label': ([list(string_types)], []),
          'only_when_empty': ([bool], False),
        })

        return tmp


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        ##display.vvv("[{}] :: url after modification: {}".format(
        ##   type(self).FILTER_ID, value
        ##))

        add_deco(value, self.get_taskparam('key'), 
           self.get_taskparam('value'),
           add_env=self.get_taskparam('add_env'),
           add_label=self.get_taskparam('add_label'),
           only_when_empty=self.get_taskparam('only_when_empty')
        )

        return value


class DecoToEnvFilter(FilterBase):

    FILTER_ID = 'deco_to_env'

    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        res = {}

        for k, v in value.get('deco', {}).items():
            envkeys = v.get('addto', {}).get('env', [])

            for ek in envkeys:
                res[ek] = v['value']

        return res


class DecoToLabelsFilter(FilterBase):

    FILTER_ID = 'deco_to_labels'

    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        res = {}

        for k, v in value.get('deco', {}).items():
            label_keys = v.get('addto', {}).get('labels', [])

            for lk in label_keys:
                res[lk] = v['value']

        return res



# ---- Ansible filters ----
class FilterModule(object):
    ''' filter related to container building '''

    def filters(self):
        res = {}

        tmp = [
           AppendContEnvFilter,
           AutoVersionPostProc,
           CombineBuildMetaFilter,
           DecoAddFilter,
           DecoToEnvFilter,
           DecoToLabelsFilter,
           PSetsFilter,
        ]

        for f in tmp:
            res[f.FILTER_ID] = f()

        return res

