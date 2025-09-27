

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'status': ['preview'],
    'supported_by': 'community'
}

import collections
import copy
import re
import os
import json

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

        mucap_spec = {
          'regex': (list(string_types), ''),
          'versions': ([collections.abc.Mapping], {}),
        }

        tmp.update({
          'multi_capture': ([collections.abc.Mapping], {}, mucap_spec),
        })

        tmeta = tmp.get(MAGIC_ARGSPECKEY_META, None) or {}
        tmp[MAGIC_ARGSPECKEY_META] = tmeta

        tmeta.setdefault('mutual_exclusions', []).append(
          ['capture_group', 'multi_capture']
        )

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
                    raise AnsibleOptionsError(errpfx + " more than one match was found")

                found_match = m.group('version')

            if not found_match:
                raise AnsibleOptionsError(errpfx + " no match was found")

            value = found_match
            return value

        mcap = self.get_taskparam('multi_capture')
        rgx = mcap['regex']
        vers = mcap['versions']

        if rgx:
            res = {'extra_tags': [], 'meta_info': {}}

            ## create final regex from regex template and defined versions
            tmp = {}

            if 'idtag' not in vers:
                raise AnsibleOptionsError(
                    "mandatory versions subkey 'idtag' missing:\n"\
                    "  {}".format(
                        json.dumps(mcap, indent=2).replace('\n', '\n  ')
                    )
                )

            for k in list(vers.keys()):
                v = vers[k]

                if not isinstance(v, collections.abc.Mapping):
                    ## assume simple pattern string
                    v = {'pattern': v}

                if k == 'idtag':
                    if v.get('optional', False):
                        raise AnsibleOptionsError(
                            "special versions subkey 'idtag' cannot be"\
                            " optional:\n  {}".format(
                                json.dumps(mcap, indent=2).replace(
                                    '\n', '\n  '
                                )
                            )
                        )

                tmp[k.upper()] = (r'(?P<' + k + '>{})').format(v['pattern'])
                vers[k] = v

            rgx_fin = rgx.format(**tmp)

            errpfx = \
               "multi capture must match exactly once, but for"\
               " given regex template '{}' and final templated"\
               " regex '{}'".format(rgx, rgx_fin)

            found_matches = {}

            for m in re.finditer(rgx_fin, value, flags=re.MULTILINE):
                if found_matches:
                    raise AnsibleOptionsError(
                        errpfx + " more than one match was found"
                    )

                for k, v in vers.items():
                    mx = m.group(k)

                    if mx:
                        found_matches[k] = mx
                        continue

                    if not v.get('optional', False):
                        raise AnsibleOptionsError(
                            "failed to find a match for mandatory versions"\
                            " subgroup '{}' using regex '{}' trying to"\
                            " match on this value:\n  '{}'".format(
                                k, rgx_fin, value
                            )
                        )

            if not found_matches:
                raise AnsibleOptionsError(errpfx + " no match was found")

            res['idtag'] = found_matches['idtag']
            res['ver_in'] = value
            return res

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
          'rmtmp': ([bool], False),
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

        rmtmp_mode = self.get_taskparam('rmtmp')

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

                tmp = v.get('temporary', False)

                if rmtmp_mode:
                    if not tmp:
                        # in temporary remove mode ignore any
                        # non temporary packages
                        continue

                    setdefault_none(v, 'modopts', {}).update(state='absent')

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

        # through filtering it is possible that we get empty psets, filter them out
        psets = list(filter(lambda x: x.get('name', False), psets))

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
          'syspath': ([collections.abc.Mapping], {}),
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

        ## handle generic env vars
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

        ## handle syspath
        curpath = value.setdefault('syspath', {})
        newpath = self.get_taskparam('syspath')

        for x in ['present', 'absent']:
            cur = setdefault_none(curpath, x, [])
            for n in newpath.get(x, []):
                if n not in cur:
                    cur.append(n)

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



class UpdateParentFilter(FilterBase):

    FILTER_ID = 'update_parent'

    @property
    def argspec(self):
        tmp = super(UpdateParentFilter, self).argspec

        tmp.update({
          'autover': ([collections.abc.Mapping],),
          'method': (list(string_types),),
          'method_args': ([collections.abc.Mapping],),
        })

        return tmp


    def _method_string_template(self, parent, av, **kwargs):
        # this method simply does a standard python str.format operation
        # on parent parts, doing standard python templating with version
        # number when parent strings are templatable
        for k,v in parent.get('auto_versioned', {}).items():
            parent[k] = v.format(AUTOVER=av['version_in'])

        return parent


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        m = self.get_taskparam('method')

        tmp = getattr(self, '_method_' + m, None)
        ansible_assert(tmp, "unsupported parent update method '{}'".format(m))

        value = tmp(value, self.get_taskparam('autover'),
          **self.get_taskparam('method_args')
        )

        return value



##
## gets a param map fitting the nsible.builtin.apt interface
## and returns a shell script which more or less does the
## same as apt module should have done
##
## TODO: support other apt-module options or at least throw error when unsupported opt given???
##
class AptInstallScriptFilter(FilterBase):

    FILTER_ID = 'to_apt_install_script'

##    @property
##    def argspec(self):
##        tmp = super(AptInstallScriptFilter, self).argspec
##
##        tmp.update({
##          'autover': ([collections.abc.Mapping],),
##          'method': (list(string_types),),
##          'method_args': ([collections.abc.Mapping],),
##        })
##
##        return tmp


    def run_specific(self, value):
        if not isinstance(value, collections.abc.Mapping):
            raise AnsibleOptionsError("filter input must be a mapping")

        ##display.vvv("AptInstallScriptFilter.run_specific: input mapping:\n{}".format(json.dumps(value, indent=2)))

        res = []

        if value.get('update_cache', False):
            res.append("apt-get update")

        plist = None

        ## go through package list param name aliases, first one hit wins
        for x in ['name', 'package', 'pkg']:
            hit = value.get(x, None)

            if hit:
                if isinstance(hit, string_types):
                    hit = [hit]

                plist = hit
                break

        ansible_assert(plist,
            "given apt install params seems not to contain a single"\
            " package to install, this seems strange:\n{}".format(
                json.dumps(value, indent=2)
            )
        )

        inst_opts = []

        if not value.get('install_recommends', False):
            inst_opts.append("--no-install-recommends")
            inst_opts.append("--no-install-suggests")

        inst_opts.append("-y")

        res.append("apt-get install {}".format(' '.join(inst_opts + plist)))
        return '\n'.join(res)



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
           UpdateParentFilter,
           AptInstallScriptFilter,
        ]

        for f in tmp:
            res[f.FILTER_ID] = f()

        return res

