"""Recover a slow package download, validating the official registry integrity."""
import base64
import hashlib
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
target=root/'.tools'/'next-16.3.8.tgz'; target.parent.mkdir(parents=True,exist_ok=True)
with httpx.Client(timeout=httpx.Timeout(90,connect=20),follow_redirects=True) as client:
    metadata=client.get('https://registry.npmjs.org/next/16.3.8').json()
    digest=hashlib.sha512(); total=0
    with client.stream('GET',metadata['dist']['tarball']) as response:
        response.raise_for_status(); print('HTTP',response.status_code,'content-length',response.headers.get('content-length'),flush=True)
        with target.open('wb') as file:
            for block in response.iter_bytes(1024*1024):
                file.write(block);digest.update(block);total+=len(block)
                print('Downloaded',round(total/1024/1024,1),'MiB',flush=True)
    actual='sha512-'+base64.b64encode(digest.digest()).decode()
    if actual!=metadata['dist']['integrity']: raise RuntimeError('Package integrity mismatch')
    print('Official registry SHA512 integrity verified',flush=True)
