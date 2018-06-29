#!/usr/bin/env python

# This file is part of onedrive-magic and distributed under the terms of the
# MIT license. See COPYING.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import argparse
import logging
import sys

import yaml

from util import googledriveclient, onedriveclient

class CLI:
    def __init__(self, args, client='microsoft'):
        parser = argparse.ArgumentParser()
        parser.add_argument('-c', '--config',
            help = 'Config file location',
            default = 'config.yaml',
        )
        parser.add_argument('-v', '--verbose',
            help = 'Enable verbose output',
            action = 'store_true',
        )
        for arg in args:
            parser.add_argument(arg)

        self.args = parser.parse_args()

        with open(self.args.config, 'r') as configfile:
            self.config = yaml.safe_load(configfile)

        self.config['args'] = self.args

        self.logger = logging.getLogger(__name__)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', '%Y-%m-%dT%H:%M:%S'))
        if self.args.verbose:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)

        if client == 'google':
            self.client = googledriveclient.GoogleDriveClient(self.config, self.logger)
        elif client == 'microsoft':
            self.client = onedriveclient.OneDriveClient(self.config, self.logger)
