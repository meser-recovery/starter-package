#!/usr/bin/env python3
"""Serve only the generated module candidate, including HTTP media ranges."""
import argparse
from functools import partial
from http.server import ThreadingHTTPServer
from serve_pilot import Handler
from module_visuals import OUT

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=4196)
    args=parser.parse_args()
    if not (OUT/'index.html').is_file(): parser.error('assemble the candidate first')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(OUT)))
    print(f'Module review: http://127.0.0.1:{args.port}/index.html',flush=True)
    server.serve_forever()
