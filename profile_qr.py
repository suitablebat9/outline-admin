"""Encode one local profile for the QRS scanner in sing-box for Apple."""
import base64
import gzip
import io
import json
import struct
import zlib

import segno


def profile_string(value):
    data = value.encode('utf-8')
    size = len(data)
    prefix = bytearray()
    while size >= 128:
        prefix.append(128 | (size & 127))
        size >>= 7
    prefix.append(size)
    return bytes(prefix) + data


def singbox_qr(name, config):
    # libbox ProfileContent v1: name, local profile type (int32), JSON.
    content = profile_string(name) + struct.pack('>I', 0) + profile_string(config)
    profile = b'\x03\x01' + gzip.compress(content, mtime=0)
    metadata = json.dumps({'filename': name + '.bpf', 'contentType': 'application/octet-stream'}).encode()
    envelope = struct.pack('>I', len(metadata)) + metadata + struct.pack('>I', len(profile)) + profile
    # A single source block contains the whole file. The Apple scanner accepts
    # bare base64, so a camera scan never navigates to a third-party website.
    compressed = zlib.compress(envelope)
    block = struct.pack('<5I', 1, 0, 1, len(compressed), zlib.crc32(envelope) ^ 1) + compressed
    qr = segno.make_qr(base64.b64encode(block).decode('ascii'), error='m')
    image = io.BytesIO()
    qr.save(image, kind='png', scale=6, border=4)
    return image.getvalue()
