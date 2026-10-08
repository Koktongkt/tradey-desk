"""Credential-free fixed-schema client for the provider-only private socket."""
import json
import socket
import sys


def main():
    try:
        if len(sys.argv) != 2:
            raise ValueError('classifier_argument_rejected')
        body = sys.stdin.buffer.read(65537)
        if len(body) > 65536:
            raise ValueError('classifier_input_limit')
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(18)
            client.connect(sys.argv[1])
            client.sendall(body)
            client.shutdown(socket.SHUT_WR)
            result = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > 131072:
                    raise ValueError('classifier_output_limit')
        row = json.loads(result)
        if not isinstance(row, dict) or set(row) != {'classifications'}:
            raise ValueError('classifier_response_rejected')
        print(json.dumps(row, allow_nan=False))
        return 0
    except Exception:
        print('provider_classifier_failed', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
