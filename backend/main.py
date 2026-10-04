import io
import os
import secrets
import time
import threading
from collections import defaultdict,deque
from pathlib import Path
from fastapi import FastAPI,Depends,Header,HTTPException,UploadFile,File,Request
from fastapi.responses import JSONResponse,FileResponse,Response
from fastapi.staticfiles import StaticFiles
from backend.service import Platform,BusinessError
from backend.schemas import DecisionInput,ExecuteInput,FeedbackInput,TrainInput
from config.settings import ROOT,DATA_PATH
from decision_models.library import create_library
from database.store import dumps
from llm.service import LLMService
from backend.access import access_info
from reward.catalog import reward_catalog

def create_app(platform=None):
    platform=platform or Platform()
    app=FastAPI(title='深谋远虑 · 营销决策平台',version='1.0.0',docs_url='/api/docs')
    app.state.platform=platform
    buckets=defaultdict(deque); rate_lock=threading.Lock()
    @app.middleware('http')
    async def harden(request:Request,call_next):
        if request.url.path.startswith('/api'):
            size=int(request.headers.get('content-length','0')) if request.headers.get('content-length','0').isdigit() else 0
            if size>int(os.getenv('MAX_UPLOAD_BYTES','2097152'))+65536:
                return JSONResponse({'detail':'上传数据过大'},413)
            key=request.client.host if request.client else 'local'
            tick=time.monotonic()
            with rate_lock:
                q=buckets[key]
                while q and tick-q[0]>60: q.popleft()
                if len(q)>=150: return JSONResponse({'detail':'请求过于频繁，请稍后再试'},429,headers={'Retry-After':'60'})
                q.append(tick)
                if len(buckets)>2000:
                    for k in list(buckets):
                        if not buckets[k] or tick-buckets[k][-1]>60: del buckets[k]
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith('/api'): response.headers['Cache-Control']='no-store'
        return response
    @app.exception_handler(BusinessError)
    async def business_error(request,exc): return JSONResponse({'detail':str(exc)},409)
    @app.exception_handler(KeyError)
    async def missing(request,exc): return JSONResponse({'detail':str(exc)},404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({'detail':str(exc)},422)

    def session_id(x_session_id:str|None=Header(None)):
        if not x_session_id or len(x_session_id)>100: raise HTTPException(401,'缺少会话，请刷新网页')
        try: platform.store.session(x_session_id)
        except KeyError: raise HTTPException(401,'会话已失效，请重新载入') from None
        return x_session_id
    def admin(request:Request,x_admin_token:str|None=Header(None)):
        token=os.getenv('ADMIN_TOKEN','')
        if token:
            if not x_admin_token or not secrets.compare_digest(x_admin_token,token): raise HTTPException(403,'训练与实验需要管理员令牌')
        elif request.client and request.client.host not in {'127.0.0.1','::1','localhost','testclient'}:
            raise HTTPException(403,'公网训练需配置 ADMIN_TOKEN')

    @app.get('/api/health')
    def health(): return {'status':'ok','algorithm':'Deep SARSA','llm_available':platform.llm.available,'version':'1.1.0'}
    @app.post('/api/session')
    def new_session(): return platform.new_session()
    @app.get('/api/company')
    def company(): return {**platform.company_profile,'records':platform.store.company_evidence()}
    @app.get('/api/access')
    def access(): return access_info()
    @app.get('/api/dashboard')
    def dashboard(sid=Depends(session_id)): return platform.dashboard(sid)
    @app.get('/api/reward')
    def reward_definition(sid=Depends(session_id)): return reward_catalog()
    @app.get('/api/data')
    def dataset(sid=Depends(session_id)):
        s=platform.store.session(sid)
        return {**s['dataset'],'state':platform.factors.build(s['metrics'],__import__('reward').PROFILES['balanced_growth'],bias={x['name']:x['score'] for x in platform.bias.analyze(s['dataset']['daily'])}),
                'registry':platform.factors.registry.list()}
    @app.post('/api/data/upload')
    async def upload(file:UploadFile=File(...),sid=Depends(session_id)):
        blob=await file.read(int(os.getenv('MAX_UPLOAD_BYTES','2097152'))+1)
        if len(blob)>int(os.getenv('MAX_UPLOAD_BYTES','2097152')): raise HTTPException(413,'CSV 最大 2 MB')
        if not (file.filename or '').lower().endswith('.csv'): raise HTTPException(422,'仅支持 CSV 文件')
        return platform.import_data(sid,blob)
    @app.post('/api/data/demo')
    def demo(sid=Depends(session_id)): return platform.import_data(sid,DATA_PATH.read_bytes(),'demo')
    @app.get('/api/data/sample.csv')
    def sample(): return FileResponse(DATA_PATH,media_type='text/csv',filename='sample_marketing.csv')
    @app.post('/api/decisions')
    def decision(body:DecisionInput,sid=Depends(session_id)): return platform.decide(sid,body)
    @app.get('/api/decisions')
    def history(sid=Depends(session_id)): return platform.store.history(sid)
    @app.post('/api/decisions/{did}/execute')
    def execute(did:str,body:ExecuteInput,sid=Depends(session_id)): return platform.execute(sid,did,body)
    @app.post('/api/decisions/{did}/feedback')
    def feedback(did:str,body:FeedbackInput,sid=Depends(session_id)): return platform.feedback(sid,did,body)
    @app.post('/api/decisions/{did}/cancel')
    def cancel(did:str,sid=Depends(session_id)): return platform.cancel(sid,did)
    @app.post('/api/decisions/{did}/finish')
    def finish(did:str,sid=Depends(session_id)): return platform.finish_cycle(sid,did)
    @app.get('/api/export/history.json')
    def export(sid=Depends(session_id)):
        return Response(dumps({'decisions':platform.store.history(sid),'data_label':platform.store.session(sid)['dataset']['quality']}),
                        media_type='application/json',headers={'Content-Disposition':'attachment; filename="decision-history.json"'})
    @app.get('/api/library')
    def library(sid=Depends(session_id)): return create_library().run(platform.store.session(sid)['metrics'])
    @app.get('/api/lab')
    def lab(sid=Depends(session_id)): return platform.lab(sid)
    @app.post('/api/lab/train',dependencies=[Depends(admin)])
    def training(body:TrainInput,sid=Depends(session_id)): return platform.start_training(sid,body)
    @app.get('/api/lab/jobs/{jid}')
    def training_status(jid:str,sid=Depends(session_id)):
        job=platform.jobs.get(jid)
        if not job or job['session_id']!=sid: raise HTTPException(404,'训练任务不存在')
        return {k:v for k,v in job.items() if k!='session_id'}
    @app.get('/api/share/qr.png')
    def qr():
        import qrcode
        url=access_info()['share_url']
        if not url: raise HTTPException(409,'尚未配置手机可访问地址；不能用 127.0.0.1 生成共享二维码')
        out=io.BytesIO(); qrcode.make(url).save(out,format='PNG')
        return Response(out.getvalue(),media_type='image/png')

    frontend=ROOT/'frontend'/'out'
    if (frontend/'_next').exists(): app.mount('/_next',StaticFiles(directory=frontend/'_next'),name='next-assets')
    @app.get('/{path:path}',include_in_schema=False)
    def web(path:str):
        if path.startswith('api/'): raise HTTPException(404,'接口不存在')
        target=(frontend/path).resolve()
        if not target.is_relative_to(frontend.resolve()): raise HTTPException(404)
        if target.is_file(): return FileResponse(target)
        if (target/'index.html').exists(): return FileResponse(target/'index.html')
        if (frontend/'index.html').exists(): return FileResponse(frontend/'index.html')
        return JSONResponse({'detail':'前端尚未构建，请运行前端 build','api_docs':'/api/docs'},503)
    return app

app=create_app()
