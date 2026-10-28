"""TLS 1.3 over ordered bytes, independent of Bluetooth and sockets."""
import hashlib
import json
import ssl
import struct

LIMIT = 65536


def verification_code(pin, headset_nonce, phone_nonce):
    for value in (pin, headset_nonce, phone_nonce):
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Invalid verification transcript')
    digest = hashlib.sha256(f'framephone-link-v2\n{pin}\n{headset_nonce}\n{phone_nonce}\n'.encode('ascii')).hexdigest()[:32].upper()
    return ' '.join(digest[i:i+4] for i in range(0, 32, 4))


class TlsStream:
    """The caller checks the certificate before sending reconnect credentials."""
    def __init__(self, context=None, server=False):
        if context is None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.engine = context.wrap_bio(self.incoming, self.outgoing, server_side=server)
        self.ready = False
        self.plain = bytearray()
        self.feed(b'')

    @property
    def pin(self):
        return hashlib.sha256(self.engine.getpeercert(binary_form=True)).hexdigest()

    def feed(self, data):
        if data:
            self.incoming.write(data)
        if not self.ready:
            try:
                self.engine.do_handshake()
                self.ready = True
            except ssl.SSLWantReadError:
                return []
        while True:
            try:
                data = self.engine.read(16384)
                if not data:
                    raise ConnectionError('Bluetooth TLS closed')
                self.plain.extend(data)
                if len(self.plain) > LIMIT+4:
                    raise ValueError('TLS message exceeds limit')
            except ssl.SSLWantReadError:
                break
        messages = []
        while len(self.plain) >= 4:
            size, = struct.unpack_from('!I', self.plain)
            if not 1 <= size <= LIMIT:
                raise ValueError('Invalid TLS message length')
            if len(self.plain) < size+4:
                break
            messages.append(bytes(self.plain[4:size+4]))
            del self.plain[:size+4]
        return messages

    def send(self, payload):
        if not self.ready or not 1 <= len(payload) <= LIMIT or self.outgoing.pending+len(payload) > LIMIT:
            raise ValueError('TLS not ready or invalid message size')
        data = struct.pack('!I', len(payload))+payload
        while data:
            count = self.engine.write(data)
            data = data[count:]

    def send_json(self, value):
        self.send(b'\0'+json.dumps(value, separators=(',', ':'), allow_nan=False).encode())

    def take(self, maximum=480):
        return self.outgoing.read(min(maximum, self.outgoing.pending))
