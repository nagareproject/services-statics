# --
# Copyright (c) 2008-2023 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import mimetypes
from operator import itemgetter
import os

from nagare.server import reference
from nagare.services import plugin
from webob.exc import HTTPNotFound, HTTPOk

DEFAULT_CHUNK_SIZE = 4096


class FileHandler(object):
    PROXY_DIRECTIVE_PRIORITY = 2

    def __init__(self, filename, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        self.filename = os.path.abspath(filename)
        self.gzip = gzip
        self.chunk_size = chunk_size

    def __call__(self, chain, request, params):
        return self.generate_response(request, params['response'])

    @staticmethod
    def iter_file(filename, chunk_size=4096):
        with open(filename, 'rb') as fileobj:
            chunk = b'.'
            while chunk:
                chunk = fileobj.read(chunk_size)
                if chunk:
                    yield chunk

    def generate_response(self, request, response):
        filename = self.filename
        if self.gzip and os.path.isfile(self.filename + '.gz'):
            filename += '.gz'
        elif not os.path.isfile(filename):
            return HTTPNotFound()

        mime, _ = mimetypes.guess_type(filename)
        mime = mime or 'application/octet-stream'

        size = os.path.getsize(filename)
        time = os.path.getmtime(filename)

        res = HTTPOk(
            content_type=mime, content_length=size, app_iter=self.iter_file(filename), conditional_response=True
        )
        res.last_modified = time
        res.etag = '%s-%s-%s' % (time, size, hash(filename))

        if filename.endswith('.gz'):
            res.content_encoding = 'gzip'

        return res

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_file_directives(proxy_service, url, self.filename, self.gzip)

    def __str__(self):
        return 'file ' + self.filename


class DirHandler(object):
    PROXY_DIRECTIVE_PRIORITY = 3

    def __init__(self, dirname, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        self.dirname = os.path.abspath(dirname)
        self.gzip = gzip
        self.chunk_size = chunk_size

    def __call__(self, chain, request, params):
        return self.generate_response(request, params['response'])

    def generate_response(self, request, response, filename=None):
        filename = filename or request.path_info
        filename = os.path.normpath(os.path.join(self.dirname, *filename.split('/')))

        return self.generate_file_response(request, response, filename)

    def generate_file_response(self, request, response, filename):
        return (
            FileHandler(filename, self.gzip, self.chunk_size).generate_response(request, response)
            if filename.startswith(self.dirname + os.sep)
            else HTTPNotFound()
        )

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_dir_directives(proxy_service, url, self.dirname, self.gzip)

    def __str__(self):
        return 'directory ' + self.dirname


class AppHandler(object):
    PROXY_DIRECTIVE_PRIORITY = 0

    @staticmethod
    def __call__(chain, request, params):
        return chain.next(request=request, **params)

    def __str__(self):
        return 'application'

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url)


class WebSocketHandler(object):
    PROXY_DIRECTIVE_PRIORITY = 1

    def __init__(self, on_connect):
        self.on_connect = on_connect

    def __call__(self, _, request, params):
        self.on_connect(request=request, **params)

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_ws_directives(proxy_service, url)

    def __str__(self):
        return 'websocket'


class Handler(object):
    PROXY_DIRECTIVE_PRIORITY = 0

    def __init__(self, handler):
        self.handler = handler

    def __call__(self, _, request, params):
        return self.handler(request=request, **params)

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url, url)

    def __str__(self):
        return 'handler {}:{}'.format(self.handler.__module__, self.handler.__name__)


class Statics(plugin.Plugin):
    CONFIG_SPEC = dict(
        plugin.Plugin.CONFIG_SPEC,
        files={'___many___': 'string'},
        directories={'___many___': 'string'},
        mountpoints={'___many___': 'string'},
    )
    LOAD_PRIORITY = 30

    def __init__(self, name, dist, files=None, directories=None, mountpoints=None, **config):
        super(Statics, self).__init__(
            name, dist, files=files, directories=directories, mountpoints=mountpoints, **config
        )
        self._mountpoints = []

        for route, filename in (files or {}).items():
            self.register_file(route, filename)

        for route, dirname in (directories or {}).items():
            self.register_dir(route, dirname)

        for route, app_ref in (mountpoints or {}).items():
            self.register_handler(route, reference.load_object(app_ref)[0])

    def register(self, url, handler):
        url = url.strip('/')
        url = ('/%s/' % url) if url else '/'

        if url in map(itemgetter(0), self._mountpoints):
            raise ValueError('URL `{}` already registered'.format(url))

        self._mountpoints.append((url, handler))
        self._mountpoints.sort(key=lambda e: len(e[0]), reverse=True)

    def register_file(self, url, filename, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        if os.path.isfile(filename):
            self.register(url, FileHandler(filename, gzip, chunk_size))

    def register_dir(self, url, dirname, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        if os.path.isdir(dirname):
            self.register(url, DirHandler(dirname, gzip, chunk_size))

    def register_app(self, url):
        self.register(url, AppHandler())

    def register_ws(self, url, on_connect):
        self.register(url, WebSocketHandler(on_connect))

    def register_handler(self, url, handler):
        self.register(url, Handler(handler))

    @property
    def mountpoints(self):
        return [
            (url.rstrip('/') or '/', handler)
            for url, handler in sorted(self._mountpoints or [], key=itemgetter(0), reverse=True)
        ]

    def generate_proxy_directives(self, proxy_service, proxy):
        for url, handler in sorted(self.mountpoints, key=lambda e: (e[1].PROXY_DIRECTIVE_PRIORITY, -len(e[0]))):
            for directive in handler.generate_proxy_directives(proxy_service, proxy, url):
                yield directive

    def handle_request(self, chain, request=None, **params):
        if request is None:
            return chain.next(**params)

        path_info = request.path_info.rstrip('/')

        for url, handler in self._mountpoints:
            if (path_info + '/').startswith(url):
                request.script_name = request.script_name.rstrip('/') + url[:-1]
                request.path_info = request.path_info[len(url) - 1 :]

                response = handler(chain, request, params)
                break
        else:
            response = HTTPNotFound(comment=path_info)

        return response
