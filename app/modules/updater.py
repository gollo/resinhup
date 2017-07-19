#!/usr/bin/env python3

#
# ** License **
#
# Home: http://resin.io
#
# Author: Andrei Gherzan <andrei@resin.io>
#

import logging
from .util import *
from .bootconf import *
import re
import os
import shutil
import string
import time

class Updater:
    def __init__(self, fetcher, conf):
        self.fetcher = fetcher
        self.tempRootMountpoint = self.fetcher.workspace + "/root-tempmountpoint"
        if not os.path.isdir(self.tempRootMountpoint):
            os.makedirs(self.tempRootMountpoint)
        self.tempBootMountpoint = self.fetcher.workspace + "/boot-tempmountpoint"
        if not os.path.isdir(self.tempBootMountpoint):
            os.makedirs(self.tempBootMountpoint)
        self.tempStateMountpoint = self.fetcher.workspace + "/state-tempmountpoint"
        if not os.path.isdir(self.tempStateMountpoint):
            os.makedirs(self.tempStateMountpoint)
        self.conf = conf

    # The logic here is the following:
    # Check the current root partition:
    # - if current root label is resin-root then we search for resin-updt device
    #   - if resinupdt not found then we simply increase the index for current root partition and use that
    #   - if resinupdt is found we use that device
    # - if current root label is resin-updt then we search for resin-root device
    #   - if resin-root not found then we simply decrease the index for current root partition and use that
    #   - if resin-root is found we use that device
    def toUpdateRootDevice(self):
        currentRootDevice = getRootPartition(self.conf)
        currentRootLabel = getPartitionLabel(currentRootDevice)
        if currentRootLabel == "resin-root":
            updateRootDevice = getDevice("resin-updt")
            if updateRootDevice:
                log.debug("Device to be used as rootfs update: " + updateRootDevice)
                return updateRootDevice, "resin-updt"
            else:
                match = re.match(r"(.*?)(\d+$)", currentRootDevice)
                if match:
                    root = match.groups()[0]
                    idx = match.groups()[1]
                    if int(idx) > 0:
                        updateRootDevice = str(root) + str(int(idx) + 1)
                        log.warn("We didn't find resin-updt but we guessed it as " + updateRootDevice)
                        return updateRootDevice, "resin-updt"
                log.error("Bad device path")
        elif currentRootLabel == "resin-updt":
            updateRootDevice = getDevice("resin-root")
            if updateRootDevice:
                log.debug("Device to be used as rootfs update: " + updateRootDevice)
                return updateRootDevice, "resin-root"
            else:
                match = re.match(r"(.*?)(\d+$)", currentRootDevice)
                if match:
                    root = match.groups()[0]
                    idx = match.groups()[1]
                    if int(idx) > 1:
                        updateRootDevice = str(root) + str(int(idx) - 1)
                        log.warn("We didn't find resin-updt but we guessed it as " + updateRootDevice)
                        return updateRootDevice, "resin-root"
                log.error("Bad device path")

        return None

    def unpackNewRootfs(self):
        log.info("Started to prepare new rootfs... will take a while...")

        # First we need to detect what is the device that we use as the updated rootfs
        if not self.toUpdateRootDevice():
            # This means that the current device is not labeled as it should be (old hostOS)
            # We assume this is resin-root and we rerun the update root device detection
            setDeviceLabel(getRootPartition(self.conf), "resin-root")
            if not self.toUpdateRootDevice():
                log.error("Can't find the update rootfs device")
                return False
        updateDevice, updateDeviceLabel = self.toUpdateRootDevice()

        # We need to make sure this thing is not mounted - if it is just unmount it
        if isMounted(updateDevice):
            if not umount(updateDevice):
                return False

        # Format update partition and label it accoringly
        if not formatEXT3(updateDevice, updateDeviceLabel):
            log.error("Could not format " + updateDevice + " as ext3")
            return False

        # Mount the new rootfs
        if os.path.isdir(self.tempRootMountpoint):
            if isMounted(self.tempRootMountpoint):
                if not umount(self.tempRootMountpoint):
                    return False
        else:
            os.makedirs(self.tempRootMountpoint)
        if not mount(what=updateDevice, where=self.tempRootMountpoint):
            return False

        # Unpack the rootfs
        if not self.fetcher.unpackRootfs(self.tempRootMountpoint):
            return False

        # Unpack the rootfs quirks
        if not self.fetcher.unpackQuirks(self.tempRootMountpoint):
            return False

        return True

    def rootfsOverlay(self):
        log.info("Started rootfs overlay...")
        root_mount = getConfigurationItem(self.conf, 'General', 'host_bind_mount')
        if not root_mount:
            root_mount = '/'

        # Read the overlay configuration and test that we have something to overlay
        overlay = getConfigurationItem(self.conf, "rootfs", "to_keep_files")
        if not overlay:
            log.warn("Nothing configured to overlay.")
            return True
        overlay = overlay.split()

        # Perform overlay
        for oitem in overlay:
            oitem = oitem.strip()
            if not oitem or oitem.startswith("#") or oitem.startswith(";"):
                continue
            oitem = oitem.split(":") # Handle cases where we have src:dst
            src = oitem[0]
            try:
                # If we got a "src:dst" format
                dst = oitem[1]
            except:
                # We got a "src" format
                dst = src
            src_full_path = os.path.normpath(root_mount + "/" + src)
            log.debug("Will overlay " + src_full_path)
            if not os.path.exists(src_full_path):
                log.warn(src_full_path + " was not found in your current mounted rootfs. Can't overlay.")
                continue
            if not safeCopy(src_full_path, self.tempRootMountpoint + dst):
                return False
            log.debug("Overlayed " + src_full_path + " in " + self.tempRootMountpoint)
        return True

    def updateRootfs(self):
        log.info("Started to update rootfs...")
        if not self.unpackNewRootfs():
            log.error("Could not unpack new rootfs.")
            return False
        if not self.rootfsOverlay():
            log.error("Could not overlay new rootfs.")
            return False
        return True

    def updateBoot(self):
        log.info("Started to upgrade boot files...")
        bootfiles = self.fetcher.getBootFiles()

        # Read the list of 'to be ignored' files in boot partition and test that we have
        # something to ignore
        ignore_files = getConfigurationItem(self.conf, "FingerPrintScanner", "boot_whitelist")
        if not ignore_files:
            log.warn("updateBoot: No files configured to be ignored.")
            return True
        ignore_files = ignore_files.split()

        # Make sure boot is mounted and RW
        bootmountpoint = getBootPartitionRwMount(self.conf, self.tempBootMountpoint)
        if not bootmountpoint:
            return False

        for bootfile in bootfiles:
            # Ignore?
            if bootfile in ignore_files:
                log.warn(bootfile + " was ignored due to ignore_files configuration.")
                continue
            # All these files are relative to bootfilesdir
            src = os.path.join(self.fetcher.bootfilesdir, bootfile)
            dst = os.path.join(bootmountpoint, bootfile)
            if os.path.isfile(dst):
                if isTextFile(src) and isTextFile(dst):
                    log.warn("Test file " + bootfile + " already exists in boot partition. Will backup.")
                    try:
                        os.rename(dst, dst + ".hup.old")
                    except Exception as s:
                        log.warn("Can't backup " + dst)
                        log.warn(str(s))
                        return False
                else:
                    log.warn("Non-text file " + bootfile + " will be overwritten.")
            if not safeCopy(src, dst):
                return False
            log.debug("Copied " + src + " to " + dst)
        return True

    def fixFsLabels(self):
        log.info("Fixing the labels of all the filesystems...")

        # resin-boot
        if not getDevice("resin-boot"):
            bootdevice = getBootPartition(self.conf)
            if not bootdevice:
                return False
            if not setVFATDeviceLabel(bootdevice, "resin-boot"):
                return False

        # resin-root should be already labeled in unpackNewRootfs
        if not getDevice("resin-root"):
            return False

        # resin-updt should be already labeled in unpackNewRootfs
        if not getDevice("resin-updt"):
            return False

        # resin-data
        if not getDevice("resin-data"):
            log.error("Can't label btrfs partition. You need to do it manually on host OS with: btrfs filesystem label <X> resin-data .")
            return False

        return True

    def resetPersistStates(self):
        log.info("resetPersistSates: generate it new on Boot")

        bootmountpoint = getBootPartitionRwMount(self.tempStateMountpoint)
        if not bootmountpoint:
            return False

        try:
            os.remove(os.path.join(self.tempStateMountpoint, 'remove_me_to_reset'))
        except OSError:
            log.error("Can't reset state partition.")
            return False

        return True

    def upgradeSystem(self):
        log.info("Started to upgrade system.")
        if not self.updateRootfs():
            log.error("Could not update rootfs.")
            return False
        if not self.updateBoot():
            log.error("Could not update boot.")
            return False
        if not self.fixFsLabels():
            log.error("Could not fix/setup fs labels.")
            return False
        if not self.resetPersistStates():
            log.error("Could not state partition.")
            return False
        if not configureBootloader(getRootPartition(self.conf), self.toUpdateRootDevice()[0], self.conf):
            log.error("Could not configure bootloader.")
            return False
        log.info("Finished to upgrade system.")
        return True

    def cleanup(self):
        log.info("Cleanup updater...")
        if isMounted(self.tempRootMountpoint):
            umount(self.tempRootMountpoint)
        mount(what='', where=getBootPartition(self.conf), mounttype='', mountoptions='remount,ro')
