"""Blocking media preparation, run exclusively by the bounded media worker."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .models import ForumError

MAX_UPLOAD_BYTES = 128 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_MEDIA_SECONDS = 15 * 60
PROCESS_TIMEOUT = 180
# Picker hints only. The processor below validates bytes, never the suffix.
PICKER_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp3', '.wav', '.flac',
                     '.ogg', '.oga', '.ogv', '.opus', '.mp4', '.m4a', '.m4b', '.m4v',
                     '.mov', '.mkv', '.webm', '.pdf', '.zip', '.txt', '.md', '.csv', '.json')


@dataclass(frozen=True)
class ProcessedMedia:
    path: Path
    mime: str
    kind: str
    suffix: str
    size: int
    sha256: str
    thumbnail: Path | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    captions: Path | None = None


def _result(path: Path, mime: str, kind: str, suffix: str, **values) -> ProcessedMedia:
    size = path.stat().st_size
    if not 0 < size <= MAX_UPLOAD_BYTES:
        raise ForumError('forum-error-media-size')
    with path.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    return ProcessedMedia(path, mime, kind, suffix, size, checksum, **values)


class MediaProcessor:
    def __init__(self, *, ffmpeg: str | None = None, ffprobe: str | None = None):
        self.ffmpeg = ffmpeg or shutil.which('ffmpeg')
        self.ffprobe = ffprobe or shutil.which('ffprobe')

    def process(self, source: Path, directory: Path) -> ProcessedMedia:
        if not 0 < source.stat().st_size <= MAX_UPLOAD_BYTES:
            raise ForumError('forum-error-media-size')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with source.open('rb') as stream:
            header = stream.read(32)
        if header.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a')) or (
            header.startswith(b'RIFF') and header[8:12] == b'WEBP'
        ):
            return self._image(source, directory)
        demuxer = self._container(header)
        if demuxer:
            return self._av(source, directory, demuxer)
        if header.startswith(b'%PDF-'):
            target = directory / 'content.pdf'
            shutil.copyfile(source, target)
            return _result(target, 'application/pdf', 'file', '.pdf')
        if header.startswith((b'PK\x03\x04', b'PK\x05\x06')):
            target = directory / 'content.zip'
            shutil.copyfile(source, target)
            return _result(target, 'application/zip', 'file', '.zip')
        # Plain text is downloadable only. HTML/SVG/scripts are never embedded
        # in a browser or webview, even when supplied as UTF-8 text.
        if source.stat().st_size <= 1024 * 1024:
            try:
                value = source.read_text(encoding='utf-8-sig')
            except UnicodeError:
                value = ''
            if value and all(ord(c) >= 32 or c in '\n\r\t' for c in value):
                target = directory / 'content.txt'
                target.write_text(value, encoding='utf-8', newline='\n')
                return _result(target, 'text/plain', 'file', '.txt')
        raise ForumError('forum-error-media-type')

    @staticmethod
    def _container(header: bytes) -> str | None:
        if header.startswith(b'RIFF') and header[8:12] == b'WAVE':
            return 'wav'
        if header.startswith(b'fLaC'):
            return 'flac'
        if header.startswith(b'OggS'):
            return 'ogg'
        if header.startswith(b'ID3') or len(header) >= 2 and header[0] == 255 and header[1] & 0xE0 == 0xE0:
            return 'mp3'
        if len(header) >= 12 and header[4:8] == b'ftyp':
            return 'mov'
        if header.startswith(b'\x1a\x45\xdf\xa3'):
            return 'matroska'
        return None

    @staticmethod
    def _image(source: Path, directory: Path) -> ProcessedMedia:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(source) as incoming:
                    if incoming.width * incoming.height > MAX_IMAGE_PIXELS:
                        raise ForumError('forum-error-media-size')
                    incoming.seek(0)
                    transposed = ImageOps.exif_transpose(incoming)
                    mode = 'RGBA' if 'A' in transposed.getbands() or 'transparency' in transposed.info else 'RGB'
                    # A fresh image drops EXIF (including GPS), comments and
                    # arbitrary uploaded metadata, rather than forwarding it.
                    image = Image.new(mode, transposed.size)
                    image.paste(transposed.convert(mode))
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            suffix, mime = ('.png', 'image/png') if mode == 'RGBA' else ('.jpg', 'image/jpeg')
            target, thumbnail = directory / ('content' + suffix), directory / 'thumbnail.jpg'
            image.save(target, quality=90, optimize=True)
            preview = Image.new('RGB', image.size, 'white')
            if mode == 'RGBA':
                preview.paste(image, mask=image.getchannel('A'))
            else:
                preview.paste(image)
            preview.thumbnail((480, 480), Image.Resampling.LANCZOS)
            preview.save(thumbnail, quality=80, optimize=True)
            return _result(target, mime, 'image', suffix, thumbnail=thumbnail, width=image.width, height=image.height)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ForumError('forum-error-media-type') from error

    @staticmethod
    def _run(arguments: list[str], *, timeout: int = PROCESS_TIMEOUT) -> bytes:
        try:
            result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=timeout, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise ForumError('forum-error-media-processing') from error

    def _av(self, source: Path, directory: Path, demuxer: str) -> ProcessedMedia:
        if not self.ffmpeg or not self.ffprobe:
            raise ForumError('forum-error-media-unavailable')
        input_options = ['-protocol_whitelist', 'file,pipe', '-f', demuxer]
        try:
            metadata = json.loads(self._run([self.ffprobe, '-v', 'error', *input_options,
                                            '-show_format', '-show_streams', '-of', 'json', str(source)], timeout=30))
            streams = metadata['streams']
            duration = float(metadata['format']['duration'])
        except (KeyError, TypeError, ValueError) as error:
            raise ForumError('forum-error-media-type') from error
        if not math.isfinite(duration) or not 0 < duration <= MAX_MEDIA_SECONDS:
            raise ForumError('forum-error-media-duration')
        video = next((s for s in streams if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
        audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
        arguments = [self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                     '-threads', '2', *input_options, '-i', str(source), '-map_metadata', '-1', '-map_chapters', '-1']
        if video:
            width, height = int(video.get('width', 0)), int(video.get('height', 0))
            if not 0 < width * height <= MAX_IMAGE_PIXELS:
                raise ForumError('forum-error-media-size')
            target, thumbnail = directory / 'content.mp4', directory / 'thumbnail.jpg'
            subtitle = next((s for s in streams if s.get('codec_type') == 'subtitle'
                             and s.get('codec_name') in {'mov_text', 'subrip', 'webvtt', 'ass', 'ssa', 'text'}), None)
            captions = None
            caption_arguments = []
            if subtitle:
                captions = directory / 'captions.vtt'
                self._run([*arguments, '-map', f"0:{subtitle['index']}", '-c:s', 'webvtt',
                           '-fs', str(2 * 1024 * 1024), str(captions)])
                if captions.stat().st_size >= 2 * 1024 * 1024:
                    raise ForumError('forum-error-media-size')
                caption_arguments = ['-map', f"0:{subtitle['index']}", '-c:s', 'mov_text']
            self._run([*arguments, '-map', f"0:{video['index']}", '-map', '0:a:0?',
                       *caption_arguments,
                       '-vf', "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                       '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', '-threads', '2',
                       '-fs', str(MAX_UPLOAD_BYTES + 1), str(target)])
            self._run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(target),
                       '-frames:v', '1', '-vf', 'scale=480:-2', str(thumbnail)], timeout=30)
            normalized = json.loads(self._run([self.ffprobe, '-v', 'error', '-select_streams', 'v:0',
                                               '-show_streams', '-of', 'json', str(target)], timeout=30))['streams'][0]
            return _result(target, 'video/mp4', 'video', '.mp4', thumbnail=thumbnail,
                           duration=duration, width=normalized['width'], height=normalized['height'], captions=captions)
        if audio:
            target = directory / 'content.mp3'
            self._run([*arguments, '-map', f"0:{audio['index']}", '-vn', '-c:a', 'libmp3lame', '-b:a', '128k',
                       '-ac', '2', '-ar', '44100', '-fs', str(MAX_UPLOAD_BYTES + 1), str(target)])
            return _result(target, 'audio/mpeg', 'audio', '.mp3', duration=duration)
        raise ForumError('forum-error-media-type')
