#!/usr/bin/env python

# This file is part of onedrive-magic and distributed under the terms of the
# MIT license. See COPYING.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import os
import random
import requests
import sys
import time

from hashlib import md5

import google.oauth2.service_account
import google.auth.transport.requests

class GoogleDriveClient:
    def __init__(self, config, logger):
        self.baseurl = 'https://www.googleapis.com/'
        self.config = config
        self.logger = logger

        cred_kwargs = {
            'subject': '{}@{}'.format(config['args'].user, config['domain']),
            'scopes': ['https://www.googleapis.com/auth/drive'],
        }
        if isinstance(config['google']['service_credentials'], dict):
            self.creds = google.oauth2.service_account.Credentials.from_service_account_info(
                config['google']['service_credentials'],
                **cred_kwargs
            )
        else:
            self.creds = google.oauth2.service_account.Credentials.from_service_account_file(
                config['google']['service_credentials'],
                **cred_kwargs
            )
        self.session = google.auth.transport.requests.AuthorizedSession(self.creds)

    def _request(self, verb, path, **kwargs):
        if self.baseurl not in path:
            path = ''.join([self.baseurl, path])

        kwargs['timeout'] = self.config.get('timeout', 60)
        kwargs['allow_redirects'] = False
        return self.session.request(verb, path, **kwargs)

    def request(self, verb, path, **kwargs):
        result = None
        attempt = 0
        while not result:
            try:
                result = self._request(verb, path, **kwargs)
            except requests.exceptions.ReadTimeout:
                self.logger.warn('Timed out...')

            if result.status_code in [ 429, 500 ]:
                result = None
                attempt += 1
                # Jittered backoff
                delay = random.uniform(0, min(300, 3 * 2 ** attempt))
                self.logger.warn('Throttled, sleeping for {} seconds'.format(delay))
                time.sleep(delay)
            else:
                result.raise_for_status()

        return result

    def find_item(self, name, parent = None):
        query = "name = '{}' and trashed = false".format(name)
        if parent:
            query = "{} and '{}' in parents".format(query, parent)

        response = self.request(
            'GET', 'drive/v3/files',
            params = {'q': query, 'fields': 'files(id,md5Checksum,size)'},
        )
        return response

    def create_folder(self, name, parent = None):
        existing = self.find_item(name, parent).json()
        if len(existing['files']) != 0:
            self.logger.debug('Folder already exists.')
            return existing['files'][0]['id']

        payload = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        if parent:
            payload['parents'] = [ parent ]

        return self.request(
            'POST', 'drive/v3/files',
            json = payload
        ).json()['id']

    def upload_file(self, file_name, name, parent):
        stat = os.stat(file_name)
        attempt = 0
        result = None

        while not result:
            seek = 0
            if attempt == 0:
                existing = self.find_item(name, parent).json()
                if len(existing['files']) > 0:
                    self.logger.debug('File already exists.')
                    h = md5()
                    with open(file_name, 'rb') as f:
                        while True:
                            block = f.read(64 * 1024)
                            if block:
                                h.update(block)
                            else:
                                break
                    if existing['files'][0]['md5Checksum'] == h.hexdigest():
                        self.logger.debug('Checksums match.')
                        return
                    self.logger.debug('Overwriting file.')
                    upload = self.request(
                        'PATCH',
                        'upload/drive/v3/files/{}'.format(
                            existing['files'][0]['id']
                        ),
                        params = {'uploadType': 'resumable' },
                        headers = {'X-Upload-Content-Length': str(stat.st_size)},
                    )
                else:
                    upload = self.request(
                        'POST',
                        'upload/drive/v3/files',
                        params = {'uploadType': 'resumable' },
                        headers = {
                            'X-Upload-Content-Length': str(stat.st_size)
                        },
                        json = {
                            'name': name,
                            'parents': [ parent ],
                        },
                    )
                path = upload.headers['location']
            else:
                result = self.request(
                    'PUT', path,
                    headers = {'Content-Range': '*/{}'.format(stat.st_size)}
                )
                if result.status_code == 308:
                    if 'range' in status.headers:
                        seek = status.headers['range'].split('-')[1]
                else:
                    result.raise_for_status()

            attempt += 1
            if not result or result.status_code not in [200, 201]:
                with open(file_name, 'rb') as f:
                    f.seek(seek)
                    result = self._request(
                        'PUT', path,
                        data = f,
                        headers = {
                            'Content-Range': 'bytes {}-{}/{}'.format(
                                seek,
                                stat.st_size - 1,
                                stat.st_size,
                            )
                        },
                    )
            if result.status_code == 403 or result.status_code >= 500:
                delay = random.uniform(0, min(300, 3 * 2 ** attempt))
                self.logger.warn('HTTP {}, sleeping for {} seconds'.format(
                    result.status_code,
                    delay
                ))
                time.sleep(delay)
                result = None
            elif result.status_code == 308:
                # Incomplete
                attempt = 1
                result = None
            elif result.status_code == 404:
                # Expired upload attempt
                attempt = 0
                result = None
            else:
                result.raise_for_status()