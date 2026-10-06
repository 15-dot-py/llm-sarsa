"""Use the official WeChat API for mini-program codes; never substitute a URL QR."""
import os
import threading
import time
import httpx
from fastapi import HTTPException

class WechatCode:
    def __init__(self): self.lock=threading.Lock();self.token='';self.expires=0

    def get(self):
        appid=os.getenv('WECHAT_APP_ID','');secret=os.getenv('WECHAT_APP_SECRET','')
        if not appid or not secret: raise HTTPException(503,'小程序账号尚未配置，不能生成微信小程序码')
        if os.getenv('WECHAT_RELEASE_CONFIRMED','').lower()!='true':
            raise HTTPException(409,'小程序尚未完成发布，不能提供正式版小程序码')
        try:
            with self.lock:
                if time.monotonic()>=self.expires:
                    value=httpx.get('https://api.weixin.qq.com/cgi-bin/token',params={'grant_type':'client_credential','appid':appid,'secret':secret},timeout=15)
                    value.raise_for_status();body=value.json()
                    if not body.get('access_token'): raise ValueError('no token')
                    self.token=body['access_token'];self.expires=time.monotonic()+max(60,int(body.get('expires_in',7200))-300)
                token=self.token
            result=httpx.post('https://api.weixin.qq.com/wxa/getwxacodeunlimit',params={'access_token':token},
                json={'scene':'entry','page':'pages/home/index','env_version':'release','check_path':True,'width':430},timeout=15)
            result.raise_for_status()
            if result.headers.get('content-type','').startswith('application/json'): raise ValueError('wechat rejected code')
            if not (result.content.startswith(b'\x89PNG\r\n\x1a\n') or result.content.startswith(b'\xff\xd8')): raise ValueError('not image')
            return result.content,'image/png' if result.content.startswith(b'\x89PNG') else 'image/jpeg'
        except (httpx.HTTPError,ValueError,TypeError,KeyError):
            raise HTTPException(503,'微信未返回可用小程序码，请检查账号及发布状态') from None
