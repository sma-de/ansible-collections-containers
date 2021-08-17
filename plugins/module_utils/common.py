
from ansible_collections.smabot.base.plugins.module_utils.utils.dicting import setdefault_none


DOCKER_CFG_DEFAULTVAR = "docker_build"


def add_deco(deco_cfg, key, value, 
    add_env=None, add_label=None, only_when_empty=False
):
    deco = deco_cfg['deco']

    tmp = setdefault_none(deco, key, {})
    tmp['value'] = value

    tmp = setdefault_none(tmp, 'addto', {})
    env = setdefault_none(tmp, 'env', [])
    lbl = setdefault_none(tmp, 'labels', [])

    if add_env and (not env or not only_when_empty):
        env += add_env

    if add_label and (not lbl or not only_when_empty):
        lbl += add_label

