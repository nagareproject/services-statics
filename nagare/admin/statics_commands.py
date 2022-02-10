# --
# Copyright (c) 2008-2022 Net-ng.
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

    @staticmethod
    def run(statics_service):
        mountpoints = statics_service.mountpoints

        print('Mountpoints')
        print('-----------')
        print()

        if not mountpoints:
            print('<empty>')
        else:
            for url, handler in mountpoints:
                print('{} -> {}'.format(url, handler))

        return 0
