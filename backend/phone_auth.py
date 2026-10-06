"""Phone OTP authentication. Production has no test-code or fake SMS mode."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import httpx
from fastapi import HTTPException

COOKIE = 'shenmou_auth'
PRIVACY_VERSION = '2026-10-06'

def flag(name): return os.getenv(name, '').lower() in {'true', '1'}

@dataclass(frozen=True)
class AuthConfig:
    secret: str
    required: bool
    sms_enabled: bool
    storage_confirmed: bool
    secret_id: str
    secret_key: str
    app_id: str
    sign: str
    template: str
    quota: int
    quota_id: str
    free_until: float

    @classmethod
    def from_env(cls):
        try:
            expiry = datetime.fromisoformat(os.getenv('SMS_FREE_UNTIL', ''))
            until = (expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError: until = 0
        try: quota = max(0, min(200, int(os.getenv('SMS_SEND_LIMIT', '0'))))
        except ValueError: quota = 0
        return cls(os.getenv('AUTH_SECRET', ''), flag('AUTH_REQUIRE_LOGIN'), flag('SMS_SEND_ENABLED'),
                   flag('AUTH_STORAGE_CONFIRMED'), os.getenv('TENCENT_SECRET_ID', ''),
                   os.getenv('TENCENT_SECRET_KEY', ''), os.getenv('SMS_APP_ID', ''),
                   os.getenv('SMS_SIGN_NAME', ''), os.getenv('SMS_TEMPLATE_ID', ''), quota,
                   os.getenv('SMS_QUOTA_ID', ''), until)

    @property
    def ready(self):
        return bool(len(self.secret) >= 32 and self.sms_enabled and self.storage_confirmed and
                    self.secret_id and self.secret_key and self.app_id and self.sign and self.template and
                    self.quota and self.quota_id and time.time() < self.free_until)

def tc3_headers(secret_id, secret_key, payload, timestamp):
    """Tencent API v3 canonical signing, scoped to the fixed SendSms endpoint."""
    digest = lambda x: hashlib.sha256(x.encode()).hexdigest()
    date = datetime.fromtimestamp(timestamp, timezone.utc).strftime('%Y-%m-%d')
    canonical = 'POST\n/\n\ncontent-type:application/json; charset=utf-8\nhost:sms.tencentcloudapi.com\n\ncontent-type;host\n' + digest(payload)
    scope = f'{date}/sms/tc3_request'
    string = f'TC3-HMAC-SHA256\n{timestamp}\n{scope}\n{digest(canonical)}'
    sign = lambda key, value: hmac.new(key, value.encode(), hashlib.sha256).digest()
    key = sign(sign(sign(('TC3'+secret_key).encode(), date), 'sms'), 'tc3_request')
    signature = hmac.new(key, string.encode(), hashlib.sha256).hexdigest()
    return {'Authorization': f'TC3-HMAC-SHA256 Credential={secret_id}/{scope}, SignedHeaders=content-type;host, Signature={signature}',
            'Content-Type': 'application/json; charset=utf-8', 'Host': 'sms.tencentcloudapi.com',
            'X-TC-Action': 'SendSms', 'X-TC-Version': '2021-01-11', 'X-TC-Region': 'ap-guangzhou',
            'X-TC-Timestamp': str(timestamp)}

class TencentSMS:
    def __init__(self, config): self.config = config

    def send(self, phone, code, challenge):
        cfg = self.config
        body = json.dumps({'PhoneNumberSet': ['+86'+phone], 'SmsSdkAppId': cfg.app_id,
                           'SignName': cfg.sign, 'TemplateId': cfg.template,
                           'TemplateParamSet': [code], 'SessionContext': challenge},
                          ensure_ascii=False, separators=(',', ':'))
        try:
            response = httpx.post('https://sms.tencentcloudapi.com/', content=body.encode(),
                                 headers=tc3_headers(cfg.secret_id, cfg.secret_key, body, int(time.time())), timeout=15)
            response.raise_for_status()
            value = response.json().get('Response', {})
            records = value.get('SendStatusSet', [])
            if value.get('Error') or len(records) != 1 or records[0].get('Code') != 'Ok':
                raise ValueError('provider rejected message')
            if records[0].get('PhoneNumber') != '+86'+phone or records[0].get('Fee') != 1:
                raise ValueError('unexpected recipient or billing units')
            return {'provider_request_id': value.get('RequestId', ''), 'serial': records[0].get('SerialNo', '')}
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            # Never include the provider body, phone, OTP or signing headers in a user error.
            raise HTTPException(503, '验证码发送未成功，请稍后再试') from None

class PhoneAuth:
    def __init__(self, platform, config=None, sender=None, clock=None):
        self.platform = platform
        self.store = platform.store
        self.config = config or AuthConfig.from_env()
        self.sender = sender or TencentSMS(self.config)
        self.clock = clock or time.time
        with self.store.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, phone_mask TEXT NOT NULL, created REAL NOT NULL, privacy_version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_workspaces (session_id TEXT PRIMARY KEY REFERENCES sessions(id), user_id TEXT NOT NULL REFERENCES auth_users(id));
            CREATE TABLE IF NOT EXISTS auth_tokens (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES auth_users(id), expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS auth_codes (id TEXT PRIMARY KEY, phone_key TEXT NOT NULL, ip_key TEXT NOT NULL, code_hash TEXT NOT NULL,
                created REAL NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, quota_id TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS auth_codes_phone ON auth_codes(phone_key,created);
            CREATE INDEX IF NOT EXISTS auth_codes_ip ON auth_codes(ip_key,created);
            ''')

    def keyed(self, kind, value):
        return hmac.new(self.config.secret.encode(), (kind+':'+value).encode(), hashlib.sha256).hexdigest()

    def status(self):
        return {'login_required': self.config.required, 'sms_ready': self.config.ready,
                'privacy_version': PRIVACY_VERSION, 'message': '使用手机号和短信验证码登录' if self.config.ready else
                '短信登录尚未开通，暂时无法发送验证码', 'wechat_configured': bool(os.getenv('WECHAT_APP_ID') and os.getenv('WECHAT_APP_SECRET'))}

    def request_code(self, phone, ip):
        if not self.config.ready: raise HTTPException(503, '短信登录尚未开通，暂时无法发送验证码')
        if not re.fullmatch(r'1[3-9]\d{9}', phone): raise HTTPException(422, '请输入有效的中国大陆手机号')
        tick = self.clock(); pk = self.keyed('phone', phone); ik = self.keyed('ip', ip)
        challenge = secrets.token_urlsafe(32); code = f'{secrets.randbelow(1000000):06d}'
        code_hash = self.keyed('otp', challenge+':'+pk+':'+code)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            recent = c.execute('SELECT created FROM auth_codes WHERE phone_key=? ORDER BY created DESC LIMIT 1', (pk,)).fetchone()
            if recent and tick-recent[0] < 60: raise HTTPException(429, '请等待 60 秒后再获取验证码', headers={'Retry-After':'60'})
            count = c.execute('SELECT COUNT(*) FROM auth_codes WHERE phone_key=? AND created>?', (pk,tick-86400)).fetchone()[0]
            ips = c.execute('SELECT COUNT(*) FROM auth_codes WHERE ip_key=? AND created>?', (ik,tick-3600)).fetchone()[0]
            if count >= 5 or ips >= 10: raise HTTPException(429, '验证码请求过于频繁，请稍后再试')
            used = c.execute('SELECT COUNT(*) FROM auth_codes WHERE quota_id=?', (self.config.quota_id,)).fetchone()[0]
            if used >= self.config.quota: raise HTTPException(503, '本次短信试用额度已用完，暂时无法发送验证码')
            c.execute('INSERT INTO auth_codes(id,phone_key,ip_key,code_hash,created,expires,status,quota_id) VALUES (?,?,?,?,?,?,?,?)',
                      (challenge,pk,ik,code_hash,tick,tick+300,'sending',self.config.quota_id))
        try: self.sender.send(phone, code, challenge)
        except Exception:
            with self.store.connect() as c: c.execute("UPDATE auth_codes SET status='failed' WHERE id=?", (challenge,))
            # Ambiguous provider timeouts still count against the cap: never automatically resend.
            raise HTTPException(503, '验证码发送未成功，请稍后再试') from None
        with self.store.connect() as c: c.execute("UPDATE auth_codes SET status='sent' WHERE id=?", (challenge,))
        return {'challenge_id': challenge, 'expires_in': 300, 'retry_after': 60,
                'message': '验证码请求已受理，请查收短信', 'provider_accepted': True}

    def verify(self, phone, challenge, code):
        if not self.config.ready: raise HTTPException(503, '短信登录尚未开通')
        tick=self.clock(); pk=self.keyed('phone',phone); good=False
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM auth_codes WHERE id=?', (challenge,)).fetchone()
            if row and row['phone_key']==pk and row['status']=='sent' and row['expires']>tick and row['attempts']<5:
                good=secrets.compare_digest(row['code_hash'], self.keyed('otp',challenge+':'+pk+':'+code))
                c.execute('UPDATE auth_codes SET attempts=attempts+1,status=? WHERE id=?', ('consumed' if good else 'sent',challenge))
            if good:
                c.execute('INSERT OR IGNORE INTO auth_users VALUES (?,?,?,?)', (pk,phone[:3]+'****'+phone[-4:],tick,PRIVACY_VERSION))
        if not good: raise HTTPException(400, '验证码不正确、已过期或已使用，请重新获取')
        token=secrets.token_urlsafe(32); expires=tick+7*86400
        with self.store.connect() as c:
            c.execute('INSERT INTO auth_tokens VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),pk,expires))
        user=self.identify(token)
        workspace=self.workspace(user)
        return {'access_token':token,'token_type':'bearer','expires_in':7*86400,
                'user':user,'session_id':workspace}

    def identify(self, token):
        if not token or len(token)>200: return None
        hashed=hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as c:
            row=c.execute('SELECT u.id,u.phone_mask FROM auth_tokens t JOIN auth_users u ON t.user_id=u.id WHERE t.hash=? AND t.expires>?', (hashed,self.clock())).fetchone()
        return dict(row) if row else None

    def workspace(self, user):
        with self.platform.lock:
            with self.store.connect() as c:
                row=c.execute('SELECT session_id FROM auth_workspaces WHERE user_id=? ORDER BY rowid DESC LIMIT 1', (user['id'],)).fetchone()
            if row: return row[0]
            sid=self.platform.new_session()['session_id'];self.bind(sid,user);return sid

    def bind(self, sid, user):
        with self.store.connect() as c: c.execute('INSERT INTO auth_workspaces VALUES (?,?)',(sid,user['id']))

    def authorize_workspace(self, sid, user):
        with self.store.connect() as c: owner=c.execute('SELECT user_id FROM auth_workspaces WHERE session_id=?', (sid,)).fetchone()
        if self.config.required or user or owner:
            if not user: raise HTTPException(401, '请先登录')
            if not owner or owner[0]!=user['id']: raise HTTPException(403, '无法访问其他账号的工作区')

    def logout(self, token):
        with self.store.connect() as c: c.execute('DELETE FROM auth_tokens WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),))

    def delete_user(self,user):
        with self.platform.lock, self.store.connect() as c:
            ids=[r[0] for r in c.execute('SELECT session_id FROM auth_workspaces WHERE user_id=?',(user['id'],))]
            c.execute('DELETE FROM auth_tokens WHERE user_id=?',(user['id'],))
            c.execute('DELETE FROM auth_workspaces WHERE user_id=?',(user['id'],))
            for sid in ids:
                if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_archive'").fetchone():
                    c.execute('DELETE FROM model_archive WHERE session_id=?',(sid,))
                c.execute('DELETE FROM transitions WHERE session_id=?',(sid,))
                c.execute('DELETE FROM decisions WHERE session_id=?',(sid,))
                c.execute('DELETE FROM sessions WHERE id=?',(sid,))
                for prefix in ['training:', 'experiments:']: c.execute('DELETE FROM metadata WHERE key=?',(prefix+sid,))
            c.execute('DELETE FROM auth_users WHERE id=?',(user['id'],))
        # Send-attempt ledger remains hashed until trial expiry, to prevent quota reset via deletion.
