import hashlib, json, sys, zipfile
from pathlib import Path
p=Path(sys.argv[1]);expected=json.loads(zipfile.ZipFile(p).read('manifest.json'))
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None,'ZIP_CRC_FAILED'
    for name,sha in expected['files'].items():
        assert hashlib.sha256(z.read(name)).hexdigest()==sha,name
    assert set(z.namelist())==set(expected['files'])|{'manifest.json'}
print('PASS',expected['version'],len(expected['files']),'members',hashlib.sha256(p.read_bytes()).hexdigest())