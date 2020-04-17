# --
# Copyright (c) 2008-2020 Net-ng.
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


class DirServer(object):

    def __init__(self, dirname):
        self.dirname = os.path.abspath(dirname)

    @staticmethod
    def iter_file(filename, chunk_size=4096):
        with open(filename, 'rb') as fileobj:
            chunk = b'.'
            while chunk:
                chunk = fileobj.read(chunk_size)
                if chunk:
                    yield chunk

    def __call__(self, request, **params):
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

    def __str__(self):
        return self.dirname


class Statics(plugin.Plugin):
    LOAD_PRIORITY = 30

    def __init__(self, name, dist, **config):
        super(Statics, self).__init__(name, dist, **config)
        self.routes = []

    def register_dir(self, url, dirname):
        if os.path.isdir(dirname):
            self.register(url, DirServer(dirname))

    def register(self, url, app=None):
        url = url.strip('/')
        url = ('/%s/' % url) if url else '/'

        if url in map(itemgetter(0), self.routes):
            raise ValueError('URL `{}` already registered'.format(url))

        self.routes.append((url, app))
        self.routes.sort(key=lambda e: len(e[0]), reverse=True)

    def format_info(self):
        yield 'Routes:'
        for url, dirname in sorted(self.routes, key=itemgetter(0)):
            yield '  {} -> {}'.format(url.rstrip('/'), dirname or '<application>')

    def handle_request(self, chain, request=None, **params):
        if request is None:
            return chain.next(**params)

        path_info = request.path_info.rstrip('/')

        for url, app in self.routes:
            if (path_info + '/').startswith(url):
                request.script_name = request.script_name.rstrip('/') + url[:-1]
                request.path_info = request.path_info[len(url) - 1:]

                response = (app or chain.next)(request=request, **params)
                break
        else:
            response = exc.HTTPNotFound(comment=path_info)

        return response
