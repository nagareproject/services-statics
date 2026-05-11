# --
# Copyright (c) 2014-2026 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import os
import queue
import mimetypes
import selectors
import threading
from operator import itemgetter

from ws4py import manager, websocket
from webob.exc import HTTPOk, HTTPNotFound
from ws4py.server.wsgiutils import WebSocketWSGIApplication

from nagare.server import reference
from nagare.services import plugin

DEFAULT_CHUNK_SIZE = 4096


class FileHandler:
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
        return f'file {self.filename} [gzip={self.gzip},chunk_size={self.chunk_size}]'


class DirHandler:
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
        return f'directory {self.dirname} [gzip={self.gzip},chunk_size={self.chunk_size}]'


class AppHandler:
    PROXY_DIRECTIVE_PRIORITY = 0

    @staticmethod
    def __call__(chain, request, params):
        return chain.next(request=request, **params)

    def __str__(self):
        return 'application'

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url)


class Selector:
    def __init__(self, timeout=0.1):
        self.timeout = timeout
        self.selector = selectors.DefaultSelector()

    def release(self):
        self.selector.close()

    def register(self, fd):
        self.selector.register(fd, selectors.EVENT_READ)

    def unregister(self, fd):
        self.selector.unregister(fd)

    def poll(self):
        for event, _ in self.selector.select(self.timeout):
            yield event.fd


class WebSocket(websocket.WebSocket):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.cond = threading.Event()

    def join(self):
        self.cond.wait()

    def closed(self, close, reason=None):
        self.on_close(close, reason)
        self.cond.set()

    def close_connection(self):
        pass


class WebSocketHandler(manager.WebSocketManager):
    PROXY_DIRECTIVE_PRIORITY = 1
    POLLER_FACTORY = Selector

    def __init__(self, on_connect, on_receive, on_close):
        super().__init__(self.POLLER_FACTORY())

        self.websocket_factory = type(
            'WebSocket',
            (WebSocket,),
            {
                'opened': lambda self: on_connect(self),
                'received_message': lambda self, msg: on_receive(self, msg),
                'on_close': lambda self, code, reason=None: on_close(self, code, reason),
            },
        )

    def __call__(self, chain, request, params):
        environ = request.environ

        WebSocketWSGIApplication(handler_cls=self.websocket_factory)(
            environ,
            lambda msg, headers: environ['ws4py.socket'].sendall(
                'HTTP/1.1 {}\r\n{}\r\n\r\n'.format(
                    msg, '\r\n'.join(f'{name}: {value}' for name, value in headers)
                ).encode('utf-8')
            ),
        )

        websocket = environ['ws4py.websocket']
        self.add(websocket)

        if not self.is_alive():
            self.start()

        websocket.join()
        return params['response']

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_ws_directives(proxy_service, url)

    def __str__(self):
        return 'websocket'


class SSEStream:
    def __init__(self, heartbeat=None):
        self.heartbeat = heartbeat

        self.id = 0
        self.queue = queue.Queue()

    @staticmethod
    def format_event(event, data=''):
        return f'event: {event}\ndata: {data}'

    def send(self, msg):
        self.queue.put(msg)

    def send_event(self, event, data):
        self.send(self.format_event(event, data))

    def __next__(self):
        try:
            msg = self.queue.get(timeout=self.heartbeat)
        except queue.Empty:
            msg = self.format_event('ping')

        self.id += 1
        return f'id: {self.id}\n{msg}\n\n'.encode('utf-8')

    def __iter__(self):
        return self


class SSEHandler:
    PROXY_DIRECTIVE_PRIORITY = 0

    def __init__(self, on_open, on_close, heartbeat=3):
        self.on_open = on_open
        self.on_close = on_close
        self.heartbeat = heartbeat

        self.streams = set()

    def add(self, stream, request):
        self.streams.add(stream)
        self.broadcast('ping', '')
        self.on_open(stream, request)

    def remove(self, stream):
        self.streams.remove(stream)
        self.on_close(stream)

    def broadcast(self, event, data):
        for stream in self.streams:
            stream.send_event(event, data)

    def __call__(self, chain, request, params):
        response = params['response']

        if request.headers.get('accept', '') == 'text/event-stream':
            sse = SSEStream(self.heartbeat)
            sse.close = lambda: self.remove(sse)

            self.add(sse, request)

            response.content_type = 'text/event-stream'
            response.cache_control = 'no-cache'
            response.headers['Connection'] = 'keep-alive'

            response.app_iter = sse

        return response

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url)

    def __str__(self):
        return 'sse'


class Handler:
    PROXY_DIRECTIVE_PRIORITY = 0

    def __init__(self, handler, services):
        self.handler = handler
        self.services = services

    def __call__(self, _, request, params):
        return self.services(self.handler, request=request, **params)

    def generate_proxy_directives(self, proxy_service, proxy, url):
        return proxy.generate_app_directives(proxy_service, url, url)

    def __str__(self):
        return f'handler {self.handler.__module__}:{self.handler.__name__}'


class Statics(plugin.Plugin):
    CONFIG_SPEC = plugin.Plugin.CONFIG_SPEC | {
        'sse_heartbeat': 'float(default=3, help="`ping` command sending delay, in seconds")',
        'files': {'___many___': 'string'},
        'directories': {'___many___': 'string'},
        'mountpoints': {'___many___': 'string'},
    }
    LOAD_PRIORITY = 30

    def __init__(
        self,
        name,
        dist,
        sse_heartbeat=3,
        files=None,
        directories=None,
        mountpoints=None,
        services_service=None,
        **config,
    ):
        super().__init__(
            name,
            dist,
            sse_heartbeat=sse_heartbeat,
            files=files,
            directories=directories,
            mountpoints=mountpoints,
            **config,
        )
        self.sse_heartbeat = sse_heartbeat
        self.services = services_service
        self._mountpoints = []

        for route, filename in (files or {}).items():
            self.register_file(route, filename)

        for route, dirname in (directories or {}).items():
            self.register_dir(route, dirname)

        for route, app_ref in (mountpoints or {}).items():
            self.register_handler(route, reference.load_object(app_ref)[0])

    def register(self, url, handler):
        url = url.strip('/')
        url = f'/{url}/' if url else '/'

        if url in map(itemgetter(0), self._mountpoints):
            raise ValueError(f'URL `{url}` already registered')

        self._mountpoints.append((url, handler))
        self._mountpoints.sort(key=lambda e: len(e[0]), reverse=True)

        return handler

    def register_file(self, url, filename, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        if not os.path.isfile(filename):
            return None

        return self.register(url, FileHandler(filename, gzip, chunk_size))

    def register_dir(self, url, dirname, gzip=False, chunk_size=DEFAULT_CHUNK_SIZE):
        if not os.path.isdir(dirname):
            return None

        return self.register(url, DirHandler(dirname, gzip, chunk_size))

    def register_app(self, url):
        return self.register(url, AppHandler())

    def register_ws(
        self,
        url,
        on_connect=lambda websocket: None,
        on_receive=lambda wesocket, msg: None,
        on_close=lambda websocket, code, reason: None,
    ):
        return self.register(url, WebSocketHandler(on_connect, on_receive, on_close))

    def register_sse(self, url, on_connect=lambda sse, request: None, on_close=lambda sse: None):
        return self.register(url, SSEHandler(on_connect, on_close, self.sse_heartbeat))

    def register_handler(self, url, handler):
        return self.register(url, Handler(handler, self.services))

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
