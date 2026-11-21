"""Retrieve the paired Café example (source 8, clip 380) by HTTP range."""

import argparse
import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

FILE_ID = "1_JhgdZ6K3ib8xagu6QSL_NKbjIkd-lU6"
HOST = "drive.usercontent.google.com"
ARCHIVE_SIZE = 143_206_010_186
MAX_BYTES = 16 * 1024 * 1024
BLOCK = 2 * 1024 * 1024
PREFIX = "Cafe_Dataset/Dataset/cafe/8/380/"
ANNOTATION_HASH = "36543445f5c0b4bab67bef7d4890f0e1687242a05b81119903f88b4731051702"


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.allowed = False
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form":
            action = urlsplit(attributes.get("action", ""))
            self.allowed = (action.scheme, action.netloc, action.path) == ("https", HOST, "/download")
        if tag == "input" and self.allowed and attributes.get("type") == "hidden":
            name = attributes.get("name")
            if name in {"id", "export", "confirm", "uuid"}:
                self.fields[name] = attributes.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.allowed = False


class Archive:
    def __init__(self):
        request = Request(f"https://drive.google.com/uc?export=download&id={FILE_ID}",
                          headers={"Range": "bytes=0-1023", "Accept-Encoding": "identity"})
        with urlopen(request, timeout=25) as response:
            target = urlsplit(response.geturl())
            if target.scheme != "https" or target.hostname not in {"drive.google.com", HOST}:
                raise ValueError("The official archive redirected to an unexpected host.")
            if response.status == 206:
                self.url = response.geturl()
            elif "text/html" in response.headers.get("Content-Type", ""):
                form = DownloadForm()
                form.feed(response.read(65536).decode())
                if form.fields.get("id") != FILE_ID:
                    raise ValueError("The official download page has changed.")
                self.url = f"https://{HOST}/download?{urlencode(form.fields)}"
            else:
                raise ValueError("The archive did not offer a bounded download.")
        self.bytes_read = 0

    def read(self, offset: int, size: int) -> bytes:
        end = offset + size - 1
        if not 0 <= offset <= end < ARCHIVE_SIZE or self.bytes_read + size > MAX_BYTES:
            raise ValueError("The archive request would exceed the example download budget.")
        request = Request(self.url, headers={"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"})
        with urlopen(request, timeout=25) as response:
            content_range = response.headers.get("Content-Range")
            if response.status != 206 or content_range != f"bytes {offset}-{end}/{ARCHIVE_SIZE}":
                raise ValueError("Google Drive did not return the requested range for this archive version.")
            data = response.read(size + 1)
        if len(data) != size:
            raise ValueError("Google Drive returned an incomplete range.")
        self.bytes_read += size
        return data


def central_offset(archive: Archive) -> int:
    tail = archive.read(ARCHIVE_SIZE - 65536, 65536)
    position = tail.rfind(b"PK\x05\x06")
    locator = tail.rfind(b"PK\x06\x07", 0, position)
    if position < 0 or locator < 0:
        raise ValueError("Expected ZIP64 directory record is absent.")
    record = archive.read(struct.unpack_from("<Q", tail, locator + 8)[0], 56)
    if record[:4] != b"PK\x06\x06":
        raise ValueError("Invalid ZIP64 directory record.")
    return struct.unpack_from("<Q", record, 48)[0]


@dataclass(frozen=True)
class Member:
    name: str
    offset: int
    compressed: int
    expanded: int
    method: int
    crc: int


def directory(archive: Archive) -> list[Member]:
    data = archive.read(central_offset(archive), 128 * 1024)
    position = 0
    members = []
    while position + 46 < len(data):
        record = struct.unpack_from("<I6H3I5H2I", data, position)
        if record[0] != 0x02014B50:
            break
        method = record[4]
        crc, compressed, expanded, name_size, extra_size, comment_size = record[7:13]
        offset = record[-1]
        name_at = position + 46
        name = data[name_at:name_at + name_size].decode()
        position = name_at + name_size + extra_size + comment_size
        if name.startswith(PREFIX) and not name.endswith("/"):
            relative = name.removeprefix(PREFIX)
            if relative != "ann.json" and not re.fullmatch(r"images/frames_\d+\.jpg", relative):
                raise ValueError("Unexpected member in the paired example.")
            if max(expanded, compressed) > 1024 * 1024 or method not in {0, 8}:
                raise ValueError("The paired example has an unexpected file size or encoding.")
            members.append(Member(relative, offset, compressed, expanded, method, crc))
        elif members and not name.startswith(PREFIX):
            break
    if len(members) != 32:
        raise ValueError("The example clip no longer matches the archived snapshot.")
    return members


def fetch(destination: Path) -> int:
    if destination.exists():
        raise ValueError("Choose a new directory for the paired sample.")
    archive = Archive()
    members = directory(archive)
    start = min(member.offset for member in members)
    stop = max(member.offset + member.compressed + 4096 for member in members)
    data = bytearray()
    for offset in range(start, stop, BLOCK):
        data.extend(archive.read(offset, min(BLOCK, stop - offset)))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cafe-example-", dir=destination.parent) as temp:
        clip = Path(temp) / "clip"
        (clip / "images").mkdir(parents=True)
        for member in members:
            position = member.offset - start
            header = struct.unpack_from("<IHHHHHIIIHH", data, position)
            name_size, extra_size = header[-2:]
            name_at = position + 30
            if header[0] != 0x04034B50 or data[name_at:name_at + name_size].decode() != PREFIX + member.name:
                raise ValueError("A local ZIP header does not match the selected member.")
            payload_at = name_at + name_size + extra_size
            packed = data[payload_at:payload_at + member.compressed]
            if member.method == 8:
                decoder = zlib.decompressobj(-15)
                content = decoder.decompress(packed, member.expanded + 1)
                if not decoder.eof:
                    raise ValueError("The decompressed member exceeded the indexed size.")
            else:
                content = packed
            if len(content) != member.expanded or zlib.crc32(content) != member.crc:
                raise ValueError("A member failed the indexed checksum.")
            (clip / member.name).write_bytes(content)
        if hashlib.sha256((clip / "ann.json").read_bytes()).hexdigest() != ANNOTATION_HASH:
            raise ValueError("The annotation file does not match the tested clip.")
        clip.rename(destination)
    return archive.bytes_read


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        size = fetch(args.destination)
        print(f"Retrieved 31 frames and ann.json into {args.destination} using {size:,} range bytes.")
    except (OSError, ValueError, struct.error, zlib.error) as error:
        parser.exit(1, f"Sample retrieval stopped: {error}\n")
