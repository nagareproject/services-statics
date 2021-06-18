# --
# Copyright (c) 2008-2021 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import os
import mimetypes
from operator import itemgetter

from webob import exc, response
from nagare.services import plugin
from nagare.server import reference


class DirServer(object):
    PROXY_DIRECTIVE_PRIORITY = 2

    def __init__(self, dirname, gzip=False):
        self.dirname = os.path.abspath(dirname)
        self.gzip = gzip

    @staticmethod
    def iter_file(filename, chunk_size=4096):
        with open(filename, 'rb') as fileobj:
            chunk = b'.'
            while chunk:
                chunk = fileobj.read(chunk_size)
                if chunk:
                    yield chunk

    def __call__(self, _, request, params):
        filename = request.path_info
        filename = os.path.normpath(os.path.join(self.dirname, *filename.split('/')))

        if not filename.startswith(self.dirname + '/') or not os.path.isfile(filename):
            res = exc.HTTPNotFound()
        else:
            mime, _ = mimetypes.guess_type(filename)
            mime = mime or 'application/octet-stream'

            size = os.path.getsize(filename)
            time = os.path.getmtime(filename)

            res = response.Response(
                content_type=mime,
                content_length=size,
                app_iter=self.iter_file(filename),
                conditional_response=True
            )
            res.last_modified = time
            res.etag = '%s-%s-%s' % (time, size, hash(filename))

            if filename.endswith('.gz'):
                res.content_encoding = 'gzip'

        return res

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_dir_directives(proxy_service, url, self.dirname, self.gzip)

    def __str__(self):
        return self.dirname


class App(object):
    PROXY_DIRECTIVE_PRIORITY = 0

    @staticmethod
    def __call__(chain, request, params):
        return chain.next(request=request, **params)

    def __str__(self):
        return '<application>'

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url)


class WebSocket(object):
    PROXY_DIRECTIVE_PRIORITY = 1

    def __init__(self, on_connect):
        self.on_connect = on_connect

    def __call__(self, _, request, params):
        self.on_connect(request=request, **params)

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_ws_directives(proxy_service, url)

    def __str__(self):
        return '<websocket>'


class Statics(plugin.Plugin):
    CONFIG_SPEC = dict(plugin.Plugin.CONFIG_SPEC, mountpoints={'___many___': 'string'})
    LOAD_PRIORITY = 30

    def __init__(self, name, dist, mountpoints=None, **config):
        super(Statics, self).__init__(name, dist, **config)
        self.routes = []

        for route, app_ref in (mountpoints or {}).items():
            self.register(route, reference.load_object(app_ref)[0])

    def register(self, url, server):
        url = url.strip('/')
        url = ('/%s/' % url) if url else '/'

        if url in map(itemgetter(0), self.routes):
            raise ValueError('URL `{}` already registered'.format(url))

        self.routes.append((url, server))
        self.routes.sort(key=lambda e: len(e[0]), reverse=True)

    def register_dir(self, url, dirname, gzip=False):
        if os.path.isdir(dirname):
            self.register(url, DirServer(dirname, gzip))

    def register_app(self, url):
        self.register(url, App())

    def register_ws(self, url, on_connect):
        self.register(url, WebSocket(on_connect))

    def format_info(self):
        if self.routes:
            yield 'Routes:'
            for url, server in sorted(self.routes, key=itemgetter(0)):
                yield '  {} -> {}'.format(url.rstrip('/'), server)

    def generate_proxy_directives(self, proxy_service, proxy):
        for url, server in sorted(self.routes, key=lambda e: (e[1].PROXY_DIRECTIVE_PRIORITY, -len(e[0]))):
            for directive in server.generate_proxy_directives(proxy_service, proxy, url.rstrip('/')):
                yield directive

    def handle_request(self, chain, request=None, **params):
        if request is None:
            return chain.next(**params)

        path_info = request.path_info.rstrip('/')

        for url, server in self.routes:
            if (path_info + '/').startswith(url):
                request.script_name = request.script_name.rstrip('/') + url[:-1]
                request.path_info = request.path_info[len(url) - 1:]

                response = server(chain, request, params)
                break
        else:
            response = exc.HTTPNotFound(comment=path_info)

        return response
