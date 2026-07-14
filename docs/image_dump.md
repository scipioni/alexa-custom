# Board Image Dumping and Backup Guide

This guide explains how to dump a full raw SD card or eMMC disk image from a target board (e.g., `2q`) over SSH directly to your local development machine as `1q.img`.

## Dumping the Image

To back up the entire system disk (`/dev/mmcblk0`) of a remote board (hostname `2q`) to a local file (`1q.img`), run the following command from your local machine:

```bash
ssh root@2q "sudo dd if=/dev/mmcblk0 bs=4M status=progress" | dd of=1q.img status=progress
```

### How It Works

1. **`ssh root@2q "..."`**: Connects to the board `2q` as the `root` user and executes the quoted command on the remote shell.
2. **`sudo dd if=/dev/mmcblk0 bs=4M status=progress`**:
   - `if=/dev/mmcblk0`: Reads directly from the raw block device representing the eMMC/SD card.
   - `bs=4M`: Uses a block size of 4 Megabytes to optimize transfer and read throughput.
   - `status=progress`: Outputs periodic transfer statistics to stderr on the remote side.
   - The output stream of `dd` (the raw disk contents) is written to the remote stdout, which SSH pipes back to the local machine.
3. **`| dd of=1q.img status=progress`**: Pipes the incoming stream from SSH on the local machine into the local `dd` command, writing it to `1q.img` while showing local progress stats.

---

## Restoring the Image

To flash the image `1q.img` back to a block device or SD card, you can use `dd` locally (be extremely careful to specify the correct output device `of=` to avoid overwriting your host machine's drive):

```bash
sudo dd if=1q.img of=/dev/sdX bs=4M status=progress conv=fsync
```
*(Replace `/dev/sdX` with the actual block device of your target SD card reader/USB drive.)*
