#!/usr/bin/env python

# This file is part of ODM and distributed under the terms of the
# MIT license. See COPYING.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import calendar
import datetime
import json
import os
import sys
import time

import dateutil.parser

import odm.cli
import odm.ms365

def main():
    odm.cli.CLI.writer_wrap(sys)
    cli = odm.cli.CLI(['--filetree', '--upload-user', '--upload-group', '--upload-path', '--domain-map', '--limit', '--exclude', '--diff', 'file', 'action'])
    client = cli.client

    ts_start = datetime.datetime.now()
    retval = 0

    with open(cli.args.file, 'rb') as f:
        metadata = json.load(f)

    destdir = cli.args.filetree.rstrip('/') if cli.args.filetree else '/var/tmp'

    if cli.args.action == 'convert-notebooks':
        for book in metadata['notebooks']:
            client.convert_notebook(book, destdir)

    elif cli.args.action in ('download', 'download-estimate', 'list-filenames', 'upload', 'verify', 'verify-upload'):
        exclude = []
        if cli.args.exclude:
            with open(cli.args.exclude, 'rb') as f:
                exclude = [e.rstrip() for e in list(f)]

        domain_map = {}
        if cli.args.action in ('upload', 'verify-upload'):
            upload_user = cli.args.upload_user
            upload_group = cli.args.upload_group
            upload_path = None

            if upload_user:
                upload_container = odm.ms365.User(client, '{}@{}'.format(upload_user, cli.config['domain']))

            elif upload_group:
                upload_container = odm.ms365.Group(client, '{}@{}'.format(upload_group, cli.config['domain']))

            else:
                cli.logger.critical(u'No upload destination specified')
                sys.exit(1)

            upload_drive = upload_container.drive
            if not upload_drive:
                cli.logger.critical(u'Unable to find destination drive for %s', upload_container)
                sys.exit(1)

            upload_path = upload_drive.root

            if cli.args.upload_path:
                for tok in cli.args.upload_path.split('/'):
                    if upload_path:
                        upload_path = upload_path.get_folder(tok, cli.args.action == 'upload')

            if cli.args.action == 'verify-upload' and not upload_path:
                cli.logger.critical(u'Failed to verify destination folder')
                sys.exit(1)

            if cli.args.domain_map:
                for mapping in cli.args.domain_map.lower().split(','):
                    (src, dst)  = mapping.split(':')
                    domain_map[src] = dst

        size = 0
        count = 0

        for item_id in metadata['items']:
            item = metadata['items'][item_id]
            if 'file' not in item:
                continue

            item_path = client.expand_path(item_id, metadata['items'])

            if item_path in exclude:
                cli.logger.debug(u'Skipping excluded item %s', item_path)
                continue

            if cli.args.limit:
                if not item_path.startswith(cli.args.limit):
                    cli.logger.debug(u'Skipping non-matching item %s', item_path)
                    continue

            cli.logger.debug(u'Working on %s', item_path)

            if 'malware' in item:
                cli.logger.info(u'%s is tagged as malware and cannot be processed', item_path)
                continue

            size += item['size']
            count += 1

            dest = '/'.join([destdir, client.expand_path(item_id, metadata['items'], True)])

            digest = None
            if 'hashes' in item['file']:
                digest = item['file']['hashes']['quickXorHash']

            verify_args = {
                'dest': dest,
            }
            if (not cli.args.diff) or ('size' in cli.args.diff.split(',')):
                verify_args['size'] = item['size']
            if (not cli.args.diff) or ('hash' in cli.args.diff.split(',')):
                verify_args['file_hash'] = digest

            if cli.args.action == 'download':
                verify_args['strict'] = False
                if client.verify_file(**verify_args):
                    cli.logger.info(u'Verified %s', dest)
                else:
                    cli.logger.info(u'Downloading %s to %s', item_path, dest)
                    attempt = 0
                    result = None
                    while attempt < 3 and result is None:
                        attempt += 1
                        result = client.download_file(
                            item['parentReference']['driveId'],
                            item['id'],
                            dest,
                        )
                        if digest and result != digest:
                            cli.logger.info(u'%s has the wrong hash, retrying', dest)
                            result = None
                    if result is None:
                        cli.logger.warning(u'Failed to download %s', dest)
                        retval = 1
                    else:
                        os.utime(dest, (
                            time.time(),
                            calendar.timegm(dateutil.parser.parse(
                                item['fileSystemInfo']['lastModifiedDateTime']
                            ).timetuple())
                        ))

            elif cli.args.action == 'verify' and digest:
                if client.verify_file(**verify_args):
                    cli.logger.info(u'Verified %s', dest)
                else:
                    cli.logger.warning(u'Failed to verify %s', dest)
                    retval = 1

            elif cli.args.action in ('upload', 'verify-upload'):
                steps = []
                # Find parents by tracing up through references
                cur = item
                while 'upload_id' not in cur:
                    if 'id' not in cur['parentReference']:
                        # This is the root folder
                        cur['upload_id'] = upload_path
                    else:
                        steps.insert(0, cur)
                        cur = metadata['items'][cur['parentReference']['id']]

                for step in steps:
                    leaf = False
                    step_path = client.expand_path(step['id'], metadata['items'])
                    parent = metadata['items'][step['parentReference']['id']]
                    if parent['upload_id'] == 'skip':
                        cli.logger.debug(u'Skipping descendant %s', step_path)
                        step['upload_id'] = 'skip'
                        continue

                    if parent['upload_id'] == 'failed':
                        cli.logger.info(u'Failed to verify %s: parent does not exist', step_path)
                        step['upload_id'] = 'failed'
                        continue

                    if 'package' in step:
                        if step['package']['type'] != 'oneNote':
                            cli.logger.info(u'Skipping %s, unknown package type %s', step_path, step['package']['type'])
                            step['upload_id'] = 'skip'
                            continue

                        try:
                            step['upload_id'] = parent['upload_id'].get_notebook(step['name'], upload_container, cli.args.action == 'upload')
                        except TypeError:
                            step['upload_id'] = 'skip'
                            cli.logger.error(u'Failed to create notebook %s', step_path)
                            retval = 1
                            continue

                        if cli.args.action == 'verify-upload' and not step['upload_id']:
                            step['upload_id'] = 'failed'
                            retval = 1
                            continue

                    elif 'folder' in step:
                        try:
                            step['upload_id'] = parent['upload_id'].get_folder(step['name'], cli.args.action == 'upload')
                        except TypeError:
                            step['upload_id'] = 'skip'
                            cli.logger.error(u'Failed to create folder %s', step_path)
                            retval = 1
                            continue

                        if cli.args.action == 'verify-upload' and not step['upload_id']:
                            step['upload_id'] = 'failed'
                            continue

                    else:
                        leaf = True
                        if cli.args.action == 'upload':
                            step['upload_id'] = parent['upload_id'].upload_file(dest, step['name'])
                            if not step['upload_id']:
                                step['upload_id'] = 'failed'
                                cli.logger.error(u'Failed to upload %s', step_path)
                                retval = 1
                                continue
                        else:
                            if parent['upload_id'].verify_file(dest, step['name']):
                                cli.logger.info(u'Verified %s', step_path)
                            else:
                                cli.logger.warning(u'Failed to verify %s', step_path)
                                retval = 1

                    # FIXME: what should we do about missing users?
                    # FIXME: should we check to see if permissions already exist
                    # FIXME: need a CLI flag to disable permission setting
                    if cli.args.action == 'upload' and 'upload_id' in step and 'permissions' in step:
                        for perm in step['permissions']:
                            if 'link' in perm:
                                cli.logger.info(u'Skipping %s scoped shared link', perm['link']['scope'])
                                continue

                            if 'owner' in perm['roles']:
                                cli.logger.debug(u'Skipping owner permission')
                                continue

                            (user, domain) = perm['grantedTo']['user']['email'].split('@')
                            if domain in domain_map:
                                domain = domain_map[domain]

                            cli.logger.info(u'Applying permissions')
                            step['upload_id'].share(
                                '{}@{}'.format(user, domain),
                                perm['roles'],
                            )

                    # Try to keep memory usage under control by pruning leaves
                    # once they're processed.
                    if leaf:
                        step.clear()

            elif cli.args.action == 'list-filenames':
                print(item_path)

        if cli.args.action == 'download-estimate':
            delta_msg = 'wild guess time {!s}'.format(
                datetime.timedelta(seconds = int(count + (size / (24 * 1024 * 1024))))
            )
        else:
            delta_msg = 'elapsed time {!s}'.format(datetime.datetime.now() - ts_start)

        cli.logger.info(u'%.2f MiB across %d items, %s', size / (1024 ** 2), count, delta_msg)

    elif cli.args.action == 'clean-filetree':
        fullpaths = [client.expand_path(x, metadata['items'], True) for x in metadata['items'] if 'file' in metadata['items'][x]]
        for root, dirs, files in os.walk(cli.args.filetree):
            relpath = os.path.relpath(root, cli.args.filetree)
            for fname in files:
                relfpath = '/'.join([relpath, fname])
                if relfpath[:2] == './':
                    relfpath = relfpath[2:]
                if unicode(relfpath, 'utf-8') not in fullpaths:
                    cli.logger.info(u'Removing %s', relfpath)
                    fpath = '/'.join([root, fname])
                    os.unlink(fpath)

    else:
        cli.logger.critical(u'Unsupported action %s', cli.args.action)
        sys.exit(1)

    sys.exit(retval)

if __name__ == 'main':
    main()
