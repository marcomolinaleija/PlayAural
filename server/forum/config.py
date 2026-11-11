"""Explicit media transport and private storage configuration."""

import os

from .storage import LocalObjectStorage, S3ObjectStorage


def add_media_arguments(parser) -> None:
    parser.add_argument('--forum-media-url', default=os.environ.get('PLAYAURAL_FORUM_MEDIA_URL'),
                        help='Public HTTPS media URL; enables forum file uploads and playback')
    parser.add_argument('--forum-media-port', type=int, default=int(os.environ.get('PLAYAURAL_FORUM_MEDIA_PORT', '8001')),
                        help='Media HTTP listener port (default: 8001)')
    parser.add_argument('--forum-media-dir', default=os.environ.get('PLAYAURAL_FORUM_MEDIA_DIR'),
                        help='Private media/staging directory, outside the public web root; also required for object backups when HTTP is disabled')
    parser.add_argument('--forum-media-origin', action='append', default=[],
                        help='Allowed web client origin, repeat for multiple origins')


def configured_storage(directory):
    backend = os.environ.get('PLAYAURAL_FORUM_STORAGE', 'local')
    if backend == 'local':
        return LocalObjectStorage(directory)
    if backend != 's3':
        raise ValueError('PLAYAURAL_FORUM_STORAGE must be local or s3')
    bucket = os.environ.get('PLAYAURAL_FORUM_BUCKET', '')
    if not bucket:
        raise ValueError('Set PLAYAURAL_FORUM_BUCKET to a private bucket distinct from backups')
    return S3ObjectStorage(bucket, endpoint_url=os.environ.get('PLAYAURAL_FORUM_S3_ENDPOINT'),
                           region_name=os.environ.get('PLAYAURAL_FORUM_S3_REGION'))
