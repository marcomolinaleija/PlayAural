"""Small authenticated GitHub client; credentials never reach build containers."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile


REPOSITORY = 'marcomolinaleija/PlayAural'


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token_path):
        self.token_path = Path(token_path)

    def request(self, path, method='GET', body=None):
        if not path.startswith('/'):
            raise ValueError('GitHub API paths must be relative')
        headers = {'Authorization': 'Bearer ' + self.token_path.read_text().strip(),
                   'Accept': 'application/vnd.github+json', 'User-Agent': 'PlayAural-maintenance',
                   'Content-Type': 'application/json',
                   'X-GitHub-Api-Version': '2022-11-28'}
        data = json.dumps(body).encode() if body is not None else None
        return urllib.request.Request('https://api.github.com' + path, data=data, headers=headers, method=method)

    def api(self, path, method='GET', body=None):
        with urllib.request.urlopen(self.request(path, method, body), timeout=45) as response:
            content = response.read()
        return json.loads(content) if content else None

    def repo(self, suffix, method='GET', body=None):
        return self.api('/repos/' + REPOSITORY + '/' + suffix, method, body)

    def download(self, path, destination, limit=2 * 1024**3):
        request = self.request(path)
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(request, timeout=45)
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise
            location = error.headers.get('Location', '')
            parsed = urllib.parse.urlsplit(location)
            if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError('Unsafe artifact redirect')
            # New request deliberately omits Authorization on signed storage URLs.
            response = urllib.request.urlopen(location, timeout=120)
        count = 0
        temporary = Path(str(destination) + '.partial')
        with response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > limit:
                    raise ValueError('GitHub artifact exceeds the size limit')
                output.write(chunk)
        temporary.replace(destination)


def extract_windows_artifact(archive_path, destination, commit):
    expected = {'PlayAural.zip', 'sounds.zip', 'windows-release.json', 'SHA256SUMS.txt'}
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if set(names) != expected or len(names) != len(expected):
            raise ValueError('Unexpected Windows artifact contents')
        if sum(entry.file_size for entry in archive.infolist()) > 2 * 1024**3:
            raise ValueError('Windows artifact is too large')
        for name in expected:
            entry = archive.getinfo(name)
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Artifact symlinks are not allowed')
            with archive.open(name) as source, (destination / name).open('wb') as target:
                shutil.copyfileobj(source, target)
    metadata = json.loads((destination / 'windows-release.json').read_text())
    if metadata.get('source_commit') != commit:
        raise ValueError('Windows artifact source does not match the candidate')
    if set(metadata.get('sha256', {})) != {'PlayAural.zip', 'sounds.zip'}:
        raise ValueError('Windows artifact hashes are incomplete')
    for name, expected_hash in metadata['sha256'].items():
        if sha256(destination / name) != expected_hash:
            raise ValueError('Windows artifact checksum mismatch')
    with zipfile.ZipFile(destination / 'PlayAural.zip') as archive:
        for name in ('PlayAural/PlayAural.exe', 'PlayAural/updater.exe', 'PlayAural/LICENSE', 'PlayAural/THIRD_PARTY_NOTICES.md'):
            archive.getinfo(name)
        if commit.encode() not in archive.read('PlayAural/SOURCE.txt'):
            raise ValueError('Windows source notice does not match')
        if archive.testzip() is not None:
            raise ValueError('Corrupt Windows ZIP')
    return metadata
