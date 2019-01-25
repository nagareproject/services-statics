# --
# Copyright (c) 2008-2019 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from nagare.services.statics import exc, Statics


class Request(object):
    def __init__(self, path_info, script_name=''):
        self.path_info = path_info
        self.script_name = script_name


class Chain(object):
    def next(self, request):
        return request.path_info, request.script_name


def dispatch(urls, path_info, script_name):
    statics = Statics(None, None)

    if not isinstance(urls, tuple):
        urls = (urls,)

    for url in urls:
        statics.register(url)

    return statics.handle_request(Chain(), Request(path_info, script_name))


def test_empty():
    assert dispatch('', '', '') == ('', '')
    assert dispatch('', '/', '') == ('', '')
    assert dispatch('/', '', '') == ('', '')
    assert dispatch('/', '/', '') == ('', '')

    assert dispatch('', '/x', '') == ('/x', '')
    assert dispatch('', '/x/', '') == ('/x', '')
    assert dispatch('/', '/x', '') == ('/x', '')
    assert dispatch('/', '/x/', '') == ('/x', '')

    assert dispatch('', '', '/y') == ('', '/y')
    assert dispatch('', '/', '/y/') == ('', '/y')
    assert dispatch('/', '', '/y') == ('', '/y')
    assert dispatch('/', '/', '/y/') == ('', '/y')

    assert dispatch('', '/x', '/y') == ('/x', '/y')
    assert dispatch('', '/x/', '/y/') == ('/x', '/y')
    assert dispatch('/', '/x', '/y') == ('/x', '/y')
    assert dispatch('/', '/x/', '/y/') == ('/x', '/y')


def test_whole_prefix():
    assert dispatch('/demo', '/demo', '') == ('', '/demo')
    assert dispatch('/demo/', '/demo', '') == ('', '/demo')
    assert dispatch('demo/', '/demo', '') == ('', '/demo')
    assert dispatch('demo', '/demo', '') == ('', '/demo')

    assert dispatch('/demo', '/demo/', '') == ('', '/demo')
    assert dispatch('/demo/', '/demo/', '') == ('', '/demo')
    assert dispatch('demo/', '/demo/', '') == ('', '/demo')
    assert dispatch('demo', '/demo/', '') == ('', '/demo')

    assert dispatch('/demo', '/demo', '/y') == ('', '/y/demo')
    assert dispatch('/demo/', '/demo', '/y/') == ('', '/y/demo')
    assert dispatch('demo/', '/demo', '/y') == ('', '/y/demo')
    assert dispatch('demo', '/demo', '/y/') == ('', '/y/demo')


def test_prefix():
    assert dispatch('/demo', '/demo/x', '') == ('/x', '/demo')
    assert dispatch('/demo/', '/demo/x', '') == ('/x', '/demo')
    assert dispatch('demo/', '/demo/x', '') == ('/x', '/demo')
    assert dispatch('demo', '/demo/x', '') == ('/x', '/demo')

    assert dispatch('/demo', '/demo/x/', '') == ('/x', '/demo')
    assert dispatch('/demo/', '/demo/x/', '') == ('/x', '/demo')
    assert dispatch('demo/', '/demo/x/', '') == ('/x', '/demo')
    assert dispatch('demo', '/demo/x/', '') == ('/x', '/demo')

    assert dispatch('/demo', '/demo/x', '/y') == ('/x', '/y/demo')
    assert dispatch('/demo/', '/demo/x', '/y') == ('/x', '/y/demo')
    assert dispatch('demo/', '/demo/x', '/y') == ('/x', '/y/demo')
    assert dispatch('demo', '/demo/x', '/y') == ('/x', '/y/demo')

    assert dispatch('/demo', '/demo/x/', '/y') == ('/x', '/y/demo')
    assert dispatch('/demo/', '/demo/x/', '/y') == ('/x', '/y/demo')
    assert dispatch('demo/', '/demo/x/', '/y') == ('/x', '/y/demo')
    assert dispatch('demo', '/demo/x/', '/y') == ('/x', '/y/demo')


def test_not_found():
    assert dispatch('', '', '') == ('', '')
    assert dispatch('', '/x', '') == ('/x', '')

    assert isinstance(dispatch('/demo', '', ''), exc.HTTPNotFound)
    assert isinstance(dispatch('/demo', '/x', ''), exc.HTTPNotFound)


def test_sorted():
    assert dispatch(('/demo', '/demoo'), '/demo', '') == ('', '/demo')
    assert dispatch(('/demo', '/demoo'), '/demo/x/y', '') == ('/x/y', '/demo')

    assert dispatch(('/demoo', '/demo'), '/demo', '') == ('', '/demo')
    assert dispatch(('/demoo', '/demo'), '/demo/x/y', '') == ('/x/y', '/demo')

    assert dispatch(('/demo', '/demoo'), '/demoo', '') == ('', '/demoo')
    assert dispatch(('/demo', '/demoo'), '/demoo/x/y', '') == ('/x/y', '/demoo')

    assert dispatch(('/demoo', '/demo'), '/demoo', '') == ('', '/demoo')
    assert dispatch(('/demoo', '/demo'), '/demoo/x/y', '') == ('/x/y', '/demoo')
