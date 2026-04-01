#!/usr/bin/env python3
"""Serve explorer files with CORS headers."""
import http.server
import sys
import os

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_GET(self):
        # Serve hub.html as root
        if self.path == '/':
            self.path = '/hub.html'
        super().do_GET()

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    directory = sys.argv[2] if len(sys.argv) > 2 else '.'
    handler = lambda *a, **kw: CORSHandler(*a, directory=directory, **kw)
    server = http.server.HTTPServer(('0.0.0.0', port), handler)
    print(f"CORS server on :{port} serving {directory}")
    server.serve_forever()
