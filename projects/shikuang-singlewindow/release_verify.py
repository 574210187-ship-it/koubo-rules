#!/usr/bin/env python3
"""Verifies the self-contained immutable ZIP manifest (no external packages)."""
import argparse
import hashlib
import json
from pathlib import PurePosixPath
import sys
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        names=[x.filename for x in infos]
        assert len(names)==len(set(names)), 'duplicate ZIP entries'
        assert 'manifest.json' in names, 'manifest missing'
        man=json.loads(z.read('manifest.json'))
        expected={x['path']:(x['bytes'],x['sha256']) for x in man['immutable_files']}
        assert set(names)==set(expected)|{'manifest.json'}, 'unexpected or missing ZIP members'
        assert z.testzip() is None,'ZIP CRC failure'
        for name in names:
            p=PurePosixPath(name)
            assert not p.is_absolute() and '..' not in p.parts and ':' not in name,'unsafe ZIP member'
        for name,(size,hash0) in expected.items():
            content=z.read(name)
            assert len(content)==size and hashlib.sha256(content).hexdigest()==hash0, 'corrupt '+name
        return {'ok':True,'version':man['version'],'checked_files':len(expected),
                'release_sha256':hashlib.sha256(open(path,'rb').read()).hexdigest()}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('zip_path');args=a.parse_args()
    try:print(json.dumps(verify(args.zip_path),ensure_ascii=False,indent=2))
    except (AssertionError,OSError,ValueError,zipfile.BadZipFile) as e:
        print('INVALID_RELEASE: '+str(e),file=sys.stderr);sys.exit(2)