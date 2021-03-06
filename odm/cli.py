#!/usr/bin/env python3

# This file is part of ODM and distributed under the terms of the
# MIT license. See COPYING.

import argparse
import logging
import sys

import yaml

import boxsdk

from odm import googledriveclient, onedriveclient


class CLI:
    def __init__(self, args, flags=[], client='microsoft'):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            '-c', '--config',
            help='Config file location',
            default='/etc/odm.yaml',
        )
        parser.add_argument(
            '-v', '--verbose',
            help='Enable verbose output',
            action='count',
            default=0,
        )
        for arg in args:
            parser.add_argument(arg)

        for flag in flags:
            parser.add_argument(flag, action='store_true')

        self.args = parser.parse_args()

        with open(self.args.config, 'r') as configfile:
            self.config = yaml.safe_load(configfile)

        self.config['args'] = self.args

        # Configure root logger
        logger = logging.getLogger()
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter('%(asctime)s %(name)s: %(message)s', '%Y-%m-%dT%H:%M:%S'))
        if self.args.verbose == 0:
            logger.setLevel(logging.WARNING)
        elif self.args.verbose == 1:
            logger.setLevel(logging.INFO)
        else:
            logger.setLevel(logging.DEBUG)

        if self.args.verbose < 3:
            handler.addFilter(lambda x: x.name.startswith('odm'))

        logger.addHandler(handler)

        self.logger = logging.getLogger(__name__)

        self.logger.debug('Using config file %s', self.args.config)

        if client == 'google':
            self.client = googledriveclient.GoogleDriveClient(self.config)
        elif client == 'microsoft':
            self.client = onedriveclient.OneDriveClient(self.config)
        elif client == 'box':
            auth = boxsdk.JWTAuth(
                client_id=self.config['box']['clientID'],
                client_secret=self.config['box']['clientSecret'],
                enterprise_id=self.config['box']['enterpriseID'],
                jwt_key_id=self.config['box']['appAuth']['publicKeyID'],
                rsa_private_key_data=self.config['box']['appAuth']['privateKey'],
                rsa_private_key_passphrase=self.config['box']['appAuth']['passphrase'],
            )
            session = boxsdk.session.session.AuthorizedSession(
                auth,
                default_headers={
                    'Box-Notifications': 'off',
                },
            )
            self.client = boxsdk.Client(auth, session)
