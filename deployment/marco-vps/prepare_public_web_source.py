"""Restore public Git source modes before copying into an unprivileged image."""
import os
from pathlib import Path
import stat
import sys


def prepare(source):
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Release sources must be a regular directory')
    public = source / 'web_client'
    required = [source / name for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'deployment/marco-vps/nginx.conf')]
    if public.is_symlink() or not public.is_dir():
        raise ValueError('Web sources must be a regular directory')
    for path in required:
        if path.is_symlink() or not path.is_file() or any(parent.is_symlink() for parent in path.parents if parent != source and source in parent.parents):
            raise ValueError('Public image inputs must be regular source files')
    public.chmod(0o755)
    for directory, directories, files in os.walk(public, followlinks=False):
        for name in directories:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o755)
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            current = path.stat()
            if not stat.S_ISREG(current.st_mode):
                raise ValueError('Unexpected non-regular public source')
            path.chmod(0o755 if current.st_mode & 0o111 else 0o644)
    for path in required:
        path.chmod(0o644)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
    print('Public web image source permissions prepared')
