#!/usr/bin/env python3
"""Serve only the generated module candidate, including HTTP media ranges."""
import argparse
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer
from serve_pilot import Handler
from module_visuals import OUT

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=4196)
    parser.add_argument('--directory',type=Path,default=OUT,help='isolated generated candidate directory')
    args=parser.parse_args()
    directory=args.directory.resolve()
    generated=OUT.parent.resolve()
    if not directory.is_relative_to(generated):parser.error('review directory must be under tutorial/generated')
    if not (directory/'index.html').is_file(): parser.error('assemble the candidate first')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(directory)))
    print(f'Module review: http://127.0.0.1:{args.port}/index.html',flush=True)
    server.serve_forever()
