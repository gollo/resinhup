#!/usr/bin/env python3

#
# ** License **
#
# Home: http://resin.io
#
# Author: Andrei Gherzan <andrei@resin.io>
#

import logging
import os
from docker import Client
from fetcher.tar import tarFetcher
from modules.util import *
from distutils.version import StrictVersion

PRE_DOCKER_OS = "1.1.5"

log = logging.getLogger(__name__)

class dockerhubFetcher(tarFetcher):

    def __init__ (self, conffile, version, remote):
        super().__init__(conffile, version, remote)
        machine = runningDevice(conffile)

        self.remotefile = os.path.join(self.remote + ":" + version)

    def download(self):
        self.cleanworkspace()

        container_name='resinos'

        try:
            cli = Client(base_url='unix://var/run/docker.sock', version='auto')
        except:
            log.warn("Can't connect to docker daemon. Trying the rce socket...")
            return False

        # Pull docker image
        try:
            log.info("Docker image pull started... this can take a couple of minutes...")
            log.debug("Pulling " + self.remotefile + " ...")
            cli.pull(self.remotefile, stream=False)
        except:
            log.error("Can't pull update image.")
            return False

        # Make sure there is no 'resinhup' container
        try:
            cli.remove_container(container_name, force=True)
        except:
            pass

        # Create resinhup container
        try:
            cmd = '/bin/bash'
            container = cli.create_container(image=self.remotefile, command=cmd, name=container_name)
        except:
            log.error("Can't create temporary update container.")
            return False

        # Export the temporary resinhup container as tar archive
        try:
            strm = cli.export(container=container.get('Id'))
        except:
            log.error("Can't export tar archive update file.")
            return False
        self.updatefilestream = strm

        return True
