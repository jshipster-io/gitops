"""Bounded waits that detect failed disposable Jobs promptly."""
import json
import subprocess
import time

def wait_for_completion(kube, name, timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=json.loads(subprocess.check_output(kube+['get','job',name,'-o','json'],text=True))
        conditions=job.get('status',{}).get('conditions',[])
        if any(c['type']=='Complete' and c['status']=='True' for c in conditions):return
        if any(c['type']=='Failed' and c['status']=='True' for c in conditions):
            raise RuntimeError('Disposable rehearsal failed: '+name)
        time.sleep(3)
    raise TimeoutError('Disposable rehearsal timed out: '+name)
