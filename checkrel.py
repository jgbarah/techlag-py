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
import logging
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

def set_logging(args_logging, args_logfile=None):

    log_format = '%(levelname)s:%(message)s'
    if args_logging == "info":
        level = logging.INFO
    elif args_logging == "debug":
        level = logging.DEBUG
    if args_logfile:
        logging.basicConfig(format=log_format, level=level,
                            filename = args_logfile, filemode = "w")
    else:
        logging.basicConfig(format=log_format, level=level)


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
                logging.debug("Found dependencies in egg: " + egg_info[0])
                requires = req_file.read().splitlines()
        except FileNotFoundError:
            pass
        except:
            raise
    if len(requires) == 0:
        logging.debug("Dependencies not found in egg, running setup.py")
        my_dir = os.getcwd()
        os.chdir(dir)
        sys_path = sys.path
        sys.path.append(dir)
        setup = distutils.core.run_setup("setup.py", stop_after='init')
        sys.path = sys_path
        os.chdir(my_dir)
        requires = setup.install_requires
    logging.debug("Requires: " + str(requires))
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
                def is_within_directory(directory, target):
                    
                    abs_directory = os.path.abspath(directory)
                    abs_target = os.path.abspath(target)
                
                    prefix = os.path.commonprefix([abs_directory, abs_target])
                    
                    return prefix == abs_directory
                
                def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
                
                    for member in tar.getmembers():
                        member_path = os.path.join(path, member.name)
                        if not is_within_directory(path, member_path):
                            raise Exception("Attempted Path Traversal in Tar File")
                
                    tar.extractall(path, members, numeric_owner=numeric_owner) 
                    
                
                safe_extract(tar_file, extract_dir)
        elif ext == '.zip':
            with zipfile.ZipFile(BytesIO(release_stream.read())) as zip_file:
                zip_file.extractall(extract_dir)
        else:
            logging.debug("Unknown extension: " + ext)
            sys.exit(1)
        dir = get_package_dir(extract_dir)
        return get_requires(dir)


def split_dependency(dep: str) -> (str, List):
    """Split a dependency in package and specs.

    A dependency is a string (a line in requirements.txt, for example.

    :param dep: dependency string
    :return:   pair (package, list of specs)
    """

    req = next(requirements.parse(dep))
    package = req.name
    specs = [s[0]+str(semantic_version.Version.coerce(s[1])) for s in req.specs]
    spec = semantic_version.Spec(*specs)
    return (package, spec)


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

    logging.debug("Current version: " + current)
    current_file = find_source(data['releases'][str(current)])
    releases = sorted([semantic_version.Version.coerce(release) for release in data['releases'].keys()])

    to_check = spec.select(releases)
    logging.debug("Version to check: " + str(to_check))
    for count, release in enumerate(reversed(releases)):
        logging.debug(release)
        if release <= to_check:
            to_check_file = find_source(data['releases'][str(release)])
            to_check_released = datetime.datetime.strptime(to_check_file['upload_time'],
                                                           "%Y-%m-%dT%H:%M:%S")
            current_released = datetime.datetime.strptime(current_file['upload_time'],
                                                          "%Y-%m-%dT%H:%M:%S")
            lag_released = current_released - to_check_released
            dependencies = find_dependencies(to_check_file)
            return (release, count, lag_released, dependencies)


def lag_package_transitive(package: str, constraint: semantic_version.Spec, depth: int = 0):
    """Compute lag for package and all its transitive dependencies.

    Returns the release (version) considered for the package, the count of packages,
    the lag (released time) and the dependencies.

    :param package:    package to analyze
    :param constraint: constraint (semantic_version.Spec) for the package
    :param depth:      depth of the call (starts in 0, default)
    :return:           (release, count, lag_released, dependencies)
    """

    (release, count, lag_released, dependencies) = lag_package(package, constraint)
    print("  "*depth + "Package: {}, release considered: {}.".format(package, release))
    print("  "*depth + "Lag (number of releases): {}".format(count))
    print("  "*depth + "Lag (release dates): {}".format(lag_released))
    print("  "*depth + "Dependencies: {}".format(','.join(dependencies)))
    logging.debug("Dependencies: " + str(dependencies))
    for dependency in dependencies:
        (pkg, spec) = split_dependency(dependency)
        logging.debug("Going to compute lag for {} {}.".format(pkg, spec))
        (rel, c, lag_rel, dep) = lag_package_transitive(pkg, spec, depth+1)
    return (release, count, lag_released, dependencies)

parser = argparse.ArgumentParser(description='Get technical lag for a Pypi package.')
parser.add_argument("-l", "--logging", type=str, choices=["info", "debug"],
                    help="Logging level for output")
parser.add_argument("--logfile", type=str,
                    help="Log file")

parser.add_argument('package',
                    help='package to analyze')
parser.add_argument('version',
                    help='version to analyze')
args = parser.parse_args()

if args.logging:
    set_logging(args.logging, args.logfile)
logging.debug("Executed as: " + str(sys.argv))

constraint = semantic_version.Spec('==' + str(semantic_version.Version.coerce(args.version)))
(release, count, lag_released, dependencies) = lag_package_transitive(args.package, constraint)

# print("Release found: {} {}".format(args.package, release))
# print("Lag (number of releases): {}".format(count))
# print("Lag (release dates): {}".format(lag_released))
# print("Dependencies: {}".format(','.join(dependencies)))
# for dependency in dependencies:
#     (package, spec) = split_dependency(dependency)
#     print("  {}: {}".format(package, str(spec)))
#     (release, count, lag_released, dependencies) = lag_package(package, spec)
#     print("    Release found: {} {}".format(package, release))
#     print("    Lag (number of releases): {}".format(count))
#     print("    Lag (release dates): {}".format(lag_released))
#     print("    Dependencies: {}".format(','.join(dependencies)))
