#!/usr/bin/env python3

# This file is part of ODM and distributed under the terms of the
# MIT license. See COPYING.

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


class ChunkyFile():
    def __init__(self, fname, start, size):
        self.f = open(fname, 'rb')
        self.f.seek(start)
        self.len = size
        self.counter = 0

    def read(self, size):
        if self.counter >= self.len:
            return b''

        read_size = min(size, self.len - self.counter)
        ret = self.f.read(read_size)
        self.counter += len(ret)
        if self.counter >= self.len:
            self.f.close()

        return ret


def chunky_path(name):
    path = []
    while len(name.encode('utf-8')) > 255:
        # Many Unix filesystems only allow filenames <= 255 bytes. Find the
        # longest string that will fit in 255 bytes once encoded.
        for j in range(0, len(name)):
            if len(name[:j].encode('utf-8')) > 255:
                j -= 1
                break
        path.append(name[:j])
        name = name[j:]
    path.append(name)

    return path
