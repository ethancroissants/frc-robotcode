#!/usr/bin/env bash -e
# Standard pi-gen prerun: copy the previous stage's rootfs as our starting
# point if we don't already have one. Identical to the upstream stage2
# prerun.
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
