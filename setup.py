# Encoding: utf-8

# --
# Copyright (c) 2008-2018 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --

import os

from setuptools import setup, find_packages


with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as version:
    LONG_DESCRIPTION = version.read()

setup(
    name='nagare-services-statics',
    author='Net-ng',
    author_email='alain.poirier@net-ng.com',
    description='Statics publication',
    long_description=LONG_DESCRIPTION,
    license='BSD',
    keywords='',
    url='https://github.com/nagareproject/services-statics',
    packages=find_packages(),
    zip_safe=False,
    setup_requires=['setuptools_scm'],
    use_scm_version=True,
    install_requires=['WebOb', 'nagare-services'],
    entry_points='''
        [nagare.services]
        statics = nagare.services.statics:Statics
    '''
)
