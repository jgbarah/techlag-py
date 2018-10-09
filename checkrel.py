#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (C) 2018 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, 51 Franklin Street, Fifth Floor, Boston, MA 02110-1335, USA.
#
# Authors:
#     Jesus M. Gonzalez-Barahona <jgb@gsyc.urjc.es>
#

import argparse
import glob
import datetime
import distutils.core
import json
import os
import urllib.request
import urllib.parse
import sys
import tarfile
import tempfile
import zipfile

from io import BytesIO
from typing import Dict, List

import requirements
import semantic_version

from pprint import pprint

def find_source(release_data: List) -> Dict:
    """Find source information in release data

    Release data is each of the items (dictionaries) in the list
    composed by all release files for a certain release.
    This comes in data['releases'][version]

    :param release_data: list with data for a release
    :returns:            dictionary with info for a file
    """

    for file in release_data:
        if file['packagetype'] == 'sdist':
            return(file)
    return({})


def get_requires(dir: str) -> str:
    """Get requires for a extracted package

    :param dir: directory where the package is extracted
    :return:    requires, as a multi-line string
    """

    egg_info = glob.glob(dir + "/*.egg-info")
    requires = ""
    if len(egg_info) == 1:
        try:
            with open(os.path.join(egg_info[0], 'requires.txt'), 'r') as req_file:
                print("Found dependencies in egg:", egg_info[0])
                requires = req_file.read().splitlines()
        except FileNotFoundError:
            pass
        except:
            raise
    if len(requires) == 0:
        print("Dependencies not found in egg, running setup.py")
        my_dir = os.getcwd()
        os.chdir(dir)
        sys_path = sys.path
        sys.path.append(dir)
        setup = distutils.core.run_setup("setup.py", stop_after='init')
        sys.path = sys_path
        os.chdir(my_dir)
        requires = setup.install_requires
    print("Requires:", requires)
    return requires

def get_package_dir(extract_dir: str) -> str:
    """Get the module dir in the extraction directory.

    Gets the name of the directory (full path) for a extracted package,
    once it is extracted under extract_dir

    :param extract_dir: extraction directory
    :return:            directory where package is, once extracted
    """
    for path in os.listdir(extract_dir):
        dir = os.path.join(extract_dir, path)
        if os.path.isdir(dir):
            return(dir)
    return(None)


def find_dependencies(file_data: Dict):
    """Find dependencies of a Python package, given the data for its source file

    :param file_data: dictionary with data for a source release file
    """

    release_url = file_data['url']
    release_stream = urllib.request.urlopen(release_url)
    ext = os.path.splitext(urllib.parse.urlparse(release_url).path)[1]

    with tempfile.TemporaryDirectory() as extract_dir:
#    extract_dir = "/tmp/pp"
#    os.mkdir(extract_dir)
#    for p in [1]:
        if ext == '.gz':
            with tarfile.open(fileobj=release_stream, mode="r|gz") as tar_file:
                tar_file.extractall(extract_dir)
        elif ext == '.zip':
            with zipfile.ZipFile(BytesIO(release_stream.read())) as zip_file:
                zip_file.extractall(extract_dir)
        else:
            print("Unknown extension:", ext)
            sys.exit(1)
        dir = get_package_dir(extract_dir)
        return get_requires(dir)


def split_dependency(dep: str) -> (str, List):
    """Split a dependency in package and specs.

    A dependency is a string (a line in requirements.txt, for example.

    :param dep: dependency string
    :return:   pair (package, list of specs)
    """

    req = next(requirements.parse(dependency))
    package = req.name
    specs = [s[0]+str(semantic_version.Version.coerce(s[1])) for s in req.specs]
    spec = semantic_version.Spec(*specs)
    return (package, spec)


parser = argparse.ArgumentParser(description='Get technical lag for a Pypi package.')
parser.add_argument('package',
                    help='package to analyze')
parser.add_argument('version',
                    help='version to analyze')
args = parser.parse_args()

print(args.package)

def lag_package(package, spec):
    """Compute lag for a package"""

    with urllib.request.urlopen('https://pypi.org/pypi/' + package + '/json') as url:
        data = json.loads(url.read().decode())

    current = data['info']['version']
    # Normalize versions
    for release in list(data['releases']):
        normal_release = str(semantic_version.Version.coerce(release))
        if release != normal_release:
            rel_data = data['releases'][release]
            data['releases'][normal_release] = rel_data

    print("Current version:", current)
    current_file = find_source(data['releases'][str(current)])
    releases = sorted([semantic_version.Version.coerce(release) for release in data['releases'].keys()])

    to_check = spec.select(releases)
    print("Version to check:", to_check)
    for count, release in enumerate(reversed(releases)):
        print(release)
        if release <= to_check:
            to_check_file = find_source(data['releases'][str(release)])
            to_check_released = datetime.datetime.strptime(to_check_file['upload_time'],
                                                           "%Y-%m-%dT%H:%M:%S")
            current_released = datetime.datetime.strptime(current_file['upload_time'],
                                                          "%Y-%m-%dT%H:%M:%S")
            lag_released = current_released - to_check_released
            dependencies = find_dependencies(to_check_file)
            return (release, count, lag_released, dependencies)

constraint = semantic_version.Spec('==' + str(semantic_version.Version.coerce(args.version)))
(release, count, lag_released, dependencies) = lag_package(args.package, constraint)

print("Release found: {} {}".format(args.package, release))
print("Lag (number of releases): {}".format(count))
print("Lag (release dates): {}".format(lag_released))
print("Dependencies: {}".format(','.join(dependencies)))
for dependency in dependencies:
    (package, spec) = split_dependency(dependency)
    print("  {}: {}".format(package, str(spec)))
    (release, count, lag_released, dependencies) = lag_package(package, spec)
    print("    Release found: {} {}".format(package, release))
    print("    Lag (number of releases): {}".format(count))
    print("    Lag (release dates): {}".format(lag_released))
    print("    Dependencies: {}".format(','.join(dependencies)))
