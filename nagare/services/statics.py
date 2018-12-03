# --
# Copyright (c) 2008-2018 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import os
import mimetypes
from functools import partial

from webob import exc, response
from nagare.services import plugin


class Statics(plugin.Plugin):
    LOAD_PRIORITY = 30

    def __init__(self, name, dist):
        super(Statics, self).__init__(name, dist)
        self.routes = []

    def register_static(self, url, dirname):
        if os.path.isdir(dirname):
            self.register(url, os.path.abspath(dirname))

    def register(self, url, app=None):
        url = url.strip('/')
        url = ('/%s/' % url) if url else '/'

        if isinstance(app, str):
            app = partial(self.serve_file, app)

        self.routes.append((url, app))
        self.routes.sort(key=lambda e: len(e[0]), reverse=True)

    def info(self):
        super(Statics, self).info()

        print('\nRoutes:\n')
        for url, dirname in sorted(self.routes):
            print('  ', url, '->', dirname or '<application>')

    @staticmethod
    def iter_file(filename, chunk_size=4096):
        with open(filename, 'rb') as fileobj:
            chunk = b'.'
            while chunk:
                chunk = fileobj.read(chunk_size)
                if chunk:
                    yield chunk

    def serve_file(self, dirname, request, **params):
        filename = request.path_info
        filename = os.path.normpath(os.path.join(dirname, *filename.split('/')))

        if not filename.startswith(dirname + '/') or not os.path.isfile(filename):
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

        return res

    def handle_request(self, chain, request, **params):
        path_info = request.path_info.rstrip('/')

        for url, app in self.routes:
            if (path_info + '/').startswith(url):
                request.script_name = request.script_name.rstrip('/') + url[:-1]
                request.path_info = path_info[len(url) - 1:]

                response = (app or chain.next)(request=request, **params)
                break
        else:
            response = exc.HTTPNotFound(comment=path_info)

        return response
