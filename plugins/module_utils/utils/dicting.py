#!/usr/bin/env python

# TODO: copyright, owner license
#

"""
TODO module / file doc string
"""

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import collections
import copy

from ansible_collections.smabot.base.plugins.module_utils.utils.utils import ansible_assert


SUBDICT_METAKEY_ANY = '<<<|||--MATCHALL--|||>>>'


## TODO: support other merge strats, make them settable by caller??
def merge_dicts(da, db):
    ''' TODO '''

    ## note: ansible does not like raw lib import errors, so move 
    ##   import here into function so caller can handle this more 
    ##   gracefully
    import deepmerge

    merger = deepmerge.Merger(
      # pass in a list of tuple, with the
      # strategies you are looking to apply
      # to each type.
      [
          (list, ["append"]),
          ##(collections.abc.Mapping, ["merge"])
          (dict, ["merge"])
      ],
      # next, choose the fallback strategies,
      # applied to all other types:
      ["override"],
      # finally, choose the strategies in
      # the case where the types conflict:
      ["override"]
    )

    ## important: this operation always changes first dict given as param, use copy if this is an issue
    return merger.merge(da, db)


##
## note: for some unfortunate reason inheritance breaks ansible templating, so we do it here ourselves
##
def template_recursive(mapping, templater):
    ## TODO: also template keys like set_fact do
    is_map = isinstance(mapping, collections.abc.Mapping)

    if is_map:
        nm = {}
    else:
        nm = []  # assume list

    for v in mapping:

        if is_map:
            k = v
            v = mapping[k]

        v = templater.template(v)

        if isinstance(v, collections.abc.Mapping) \
        or isinstance(v, list):
            v = template_recursive(v, templater)

        if is_map:
            nm[k] = v
        else:
            nm.append(v)

    return nm


def get_subdict(d, keychain):
    ansible_assert(SUBDICT_METAKEY_ANY not in keychain, 
      "use get_subdict only with a simple keychain with just one"
      " result, use get_subdicts instead for wildcards with"
      " multiple possible results"
    )

    d = list(get_subdicts(d, keychain))

    ansible_assert(len(d) == 1, 
      "get_subdict produced more than one result, this should never happen"
    )

    return d[0][0]


def get_subdicts(d, keychain, kciter=None, kcout=None):
    if not keychain:
        yield (d, kcout)
        return

    if not kciter:
        kcout = []
        yield from get_subdicts(d, keychain, iter(keychain), kcout)
        return

    nextkeys = next(kciter, None)

    if not nextkeys:
        yield (d, kcout)
        return

    if nextkeys == SUBDICT_METAKEY_ANY:
        nextkeys = d.keys()
    else:
        nextkeys = [nextkeys]

    for k in nextkeys:
        d = d[k]
        kcout.append(k)
        yield from get_subdicts(d, keychain, kciter, copy.deepcopy(kcout))


def set_subdict(d, keychain, val):
    ansible_assert(keychain, "keychain cannot be empty when setting subdict")

    parent_kc = keychain[:-1]
    sd = get_subdict(d, parent_kc)

    sd[keychain[-1]] = val

    return d

