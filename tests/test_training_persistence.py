import time
from backend.service import Platform
from backend.schemas import TrainInput

def test_session_training_report_matches_saved_model_after_restart(tmp_path):
    p=Platform(tmp_path); sid=p.new_session()['session_id']
    job=p.start_training(sid,TrainInput(episodes=10,horizon=7,seed=7))
    deadline=time.monotonic()+30
    while p.jobs[job['id']]['status']=='running' and time.monotonic()<deadline:
        time.sleep(.05)
    assert p.jobs[job['id']]['status']=='completed'
    reload=Platform(tmp_path); lab=reload.lab(sid)
    assert len(lab['training']['curves'])==10
    assert lab['updates']==70
    assert lab['training']['model_id'] in lab['model_version']
