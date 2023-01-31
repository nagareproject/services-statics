# --
# Copyright (c) 2008-2023 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

from nagare.admin import command


class Mountpoints(command.Command):
    WITH_STARTED_SERVICES = True
    DESC = 'display URL mountpoints'

    def set_arguments(self, parser):
        parser.add_argument(
            '-u',
            '--url',
            action='append',
            dest='urls',
            metavar='URL',
            help='display the mountpoints for the given URLs',
        )

        super(Mountpoints, self).set_arguments(parser)

    @staticmethod
    def run(statics_service, urls):
        urls = {url: i for i, url in enumerate(urls or [])}

        mountpoints = statics_service.mountpoints

        if not urls:
            print('Mountpoints')
            print('-----------')
            print()

            if not mountpoints:
                print('<empty>')

        if mountpoints:
            url_maxlen = max(len(url) for url, _ in mountpoints)

            mountpoints = [e for e in mountpoints if not urls or (e[0] in urls)]
            for url, handler in sorted(mountpoints, key=lambda e: urls.get(e[0], 0)):
                print(('{2}' if urls else '{:{}} -> {}').format(url, url_maxlen, handler))

        return 0
