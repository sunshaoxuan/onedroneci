#!/usr/bin/env python3
"""Tiny HTTP CONNECT proxy for letting the VM use the host's outbound network."""
from __future__ import annotations

import select
import socket
import socketserver
import sys
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ProxyConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 3128
    connect_timeout: float = 20.0


CONFIG = ProxyConfig()


class ConnectHandler(socketserver.StreamRequestHandler):
    timeout = 30

    def handle(self) -> None:
        line = self.rfile.readline(65536).decode("iso-8859-1", "replace").strip()
        if not line:
            return
        parts = line.split()
        if len(parts) < 3 or parts[0].upper() != "CONNECT":
            self._drain_headers()
            self.wfile.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        target = parts[1]
        if ":" not in target:
            self._drain_headers()
            self.wfile.write(b"HTTP/1.1 400 Bad CONNECT target\r\n\r\n")
            return
        host, port_s = target.rsplit(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            self._drain_headers()
            self.wfile.write(b"HTTP/1.1 400 Bad port\r\n\r\n")
            return

        self._drain_headers()
        try:
            upstream = socket.create_connection((host, port), timeout=CONFIG.connect_timeout)
        except OSError as exc:
            msg = f"HTTP/1.1 502 Bad Gateway\r\nX-Proxy-Error: {exc}\r\n\r\n"
            self.wfile.write(msg.encode("utf-8", "replace"))
            return

        with upstream:
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            self.wfile.flush()
            self._tunnel(self.connection, upstream)

    def _drain_headers(self) -> None:
        while True:
            line = self.rfile.readline(65536)
            if line in (b"\r\n", b"\n", b""):
                return

    def _tunnel(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional or not readable:
                return
            for sock in readable:
                other = upstream if sock is client else client
                data = sock.recv(65536)
                if not data:
                    return
                other.sendall(data)


class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    server = ThreadedServer((CONFIG.listen_host, CONFIG.listen_port), ConnectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"CONNECT proxy listening on {CONFIG.listen_host}:{CONFIG.listen_port}", flush=True)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
