# Testing with Loopback Devices

This guide explains how to create a local BTRFS loopback device for testing the
File Revitalizer agent without risking real data.

> **Requirements:** Linux with `btrfs-progs` installed.

## Quick start

```bash
# 1. Create a 256 MB sparse image file
dd if=/dev/zero of=/tmp/btrfs-test.img bs=1M count=256

# 2. Format it as BTRFS
mkfs.btrfs -f /tmp/btrfs-test.img

# 3. Attach to a loopback device
sudo losetup --find --show /tmp/btrfs-test.img
# → prints /dev/loopN (e.g. /dev/loop0)

# 4. Mount and populate with sample files
sudo mkdir -p /mnt/btrfs-test
sudo mount /dev/loop0 /mnt/btrfs-test
sudo cp /etc/hostname /mnt/btrfs-test/
sudo cp /etc/os-release /mnt/btrfs-test/
echo "recovery test file" | sudo tee /mnt/btrfs-test/sample.txt

# 5. Simulate data loss — delete files
sudo rm /mnt/btrfs-test/sample.txt
sudo rm /mnt/btrfs-test/hostname
sync
```

## Run the agent against the loopback device

```bash
# Unmount first (agent needs raw device access)
sudo umount /mnt/btrfs-test

# Run the agent scan
./file-revitalizer-agent scan \
    --server http://localhost:8000 \
    --token YOUR_TOKEN \
    --device /dev/loop0 \
    --case-id 1
```

The agent will upload superblock, chunk-tree, root-tree, filesystem-tree, and
find-root artifacts to the Django server.

## Execute recovery commands

After the server generates recovery commands, run:

```bash
./file-revitalizer-agent execute \
    --server http://localhost:8000 \
    --token YOUR_TOKEN \
    --case-id 1 \
    --candidate-id 1
```

## Cleanup

```bash
sudo umount /mnt/btrfs-test 2>/dev/null
sudo losetup -d /dev/loop0
rm /tmp/btrfs-test.img
sudo rmdir /mnt/btrfs-test
```

## Tips

- Use `losetup -a` to list all active loopback devices.
- Use `btrfs inspect-internal dump-super /dev/loop0` to verify the device has a
  valid BTRFS superblock before running the agent.
- Increase the image size (`count=1024` for 1 GB) if you need more realistic
  file trees.
- For subvolume testing, create subvolumes before deleting files:
  ```bash
  sudo btrfs subvolume create /mnt/btrfs-test/subvol1
  sudo cp -r /usr/share/doc/bash/* /mnt/btrfs-test/subvol1/
  ```
