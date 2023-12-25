
# PBFuse (PngBinFUSE)

Explore files using FUSE (Filesystem in Userspace).
To mount, create a directory for the mount point (e.g. `mkdir mountpoint`) and navigate to this repo's root directory and run the below command:
```
python -m pbfuse mountpoint -f -s -o meta_db=meta.db
```
This will mount FUSE at `mountpoint` with database file `meta.db` and
- `-f`: run in foreground instead of background by default
- `-s`: run on a single thread (recommended)

After finished, PBFuse can be unmounted by simply using `umount` (e.g. `umount mountpoint`)

> Use `python -m pbfuse -h` to list more mount options