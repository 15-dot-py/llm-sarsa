"""Signed device-held recovery snapshots for ephemeral deployments.

Only server-issued archives are accepted. Verify the MAC before decoding any
checkpoint; never accept an arbitrary uploaded Torch pickle.
"""
import base64
import hashlib
import hmac
import json
import os
import zlib
from fastapi import HTTPException
from database.store import dumps

MAX_PACKED = 1_500_000
MAX_RAW = 16_000_000
DOMAIN = b'shenmou-workspace-v1\0'


class WorkspaceBackup:
    def __init__(self, platform, auth):
        self.platform = platform
        self.auth = auth

    @property
    def ready(self):
        return len(self.auth.config.secret) >= 32 and os.getenv('WORKSPACE_BACKUP_ENABLED', 'true').lower() == 'true'

    def _sign(self, payload):
        return hmac.new(self.auth.config.secret.encode(), DOMAIN + payload.encode('ascii'), hashlib.sha256).hexdigest()

    def export(self, sid):
        if not self.ready:
            raise HTTPException(503, '记录已保存到服务端，但浏览器恢复备份尚未启用')
        with self.platform.lock, self.platform.store.connect() as c:
            session = dict(c.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone())
            session['model'] = base64.b64encode(session['model']).decode('ascii')
            owner = c.execute('SELECT user_id FROM auth_workspaces WHERE session_id=?', (sid,)).fetchone()
            data = {'version': 1, 'session': session, 'owner': owner[0] if owner else None,
                    'decisions': [dict(r) for r in c.execute('SELECT * FROM decisions WHERE session_id=? ORDER BY created', (sid,))],
                    'transitions': [dict(r) for r in c.execute('SELECT * FROM transitions WHERE session_id=? ORDER BY created', (sid,))],
                    'training': self.platform.store.get_metadata('training:' + sid), 'archives': []}
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='model_archive'").fetchone():
                for row in c.execute('SELECT * FROM model_archive WHERE session_id=?', (sid,)):
                    value = dict(row); value['model'] = base64.b64encode(value['model']).decode('ascii')
                    data['archives'].append(value)
        raw = dumps(data).encode('utf-8')
        packed = base64.b64encode(zlib.compress(raw, 6)).decode('ascii')
        if len(raw) > MAX_RAW or len(packed) > MAX_PACKED:
            raise HTTPException(413, '工作区超过浏览器备份上限，请导出记录；服务端记录仍然保留')
        return {'version': 1, 'session_id': sid, 'updated': session['updated'],
                'payload': packed, 'signature': self._sign(packed)}

    def restore(self, archive, user):
        if not self.ready:
            raise HTTPException(503, '工作区恢复尚未启用')
        packed = archive['payload']
        if not hmac.compare_digest(self._sign(packed), archive['signature']):
            raise HTTPException(422, '备份签名无效，未恢复任何记录')
        try:
            inflater = zlib.decompressobj()
            raw = inflater.decompress(base64.b64decode(packed, validate=True), MAX_RAW + 1)
            if len(raw) > MAX_RAW or inflater.unconsumed_tail or not inflater.eof or inflater.unused_data:
                raise ValueError('archive size')
            data = json.loads(raw)
            s = data['session']; sid = s['id']
            if data['version'] != 1 or sid != archive['session_id']:
                raise ValueError('archive identity')
            for table in ('decisions', 'transitions', 'archives'):
                if any(r['session_id'] != sid for r in data[table]):
                    raise ValueError('record identity')
        except (ValueError, KeyError, TypeError, zlib.error):
            raise HTTPException(422, '备份内容无效，未恢复任何记录') from None
        owner = data['owner']
        if owner and (not user or user['id'] != owner):
            raise HTTPException(403, '请登录备份所属账号后恢复')
        if not owner and (user or self.auth.config.required):
            raise HTTPException(403, '匿名备份不能写入已登录账号')
        with self.platform.lock, self.platform.store.connect() as c:
            if c.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                self.auth.authorize_workspace(sid, user)
                return {'session_id': sid, 'restored': False, 'message': '服务端记录存在，未覆盖当前工作区'}
            # Authentication accounts are never restored from device archives.
            if owner and not c.execute('SELECT 1 FROM auth_users WHERE id=?', (owner,)).fetchone():
                raise HTTPException(403, '备份所属账号已不可用')
            model = base64.b64decode(s['model'], validate=True)
            # A valid server signature is required before this checkpoint check.
            self.platform._agent({**s, 'model': model})
            c.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)',
                      (sid, s['created'], s['updated'], s['dataset'], s['metrics'], model, s['config'], s['active_decision']))
            for r in data['decisions']:
                c.execute('INSERT INTO decisions VALUES (?,?,?,?,?)', (r['id'], sid, r['created'], r['status'], r['record']))
            for r in data['transitions']:
                c.execute('INSERT INTO transitions VALUES (?,?,?,?)', (r['id'], sid, r['created'], r['record']))
            if data['training'] is not None:
                self.platform.store.set_metadata('training:' + sid, data['training'], c)
            if data['archives']:
                c.execute('CREATE TABLE IF NOT EXISTS model_archive (session_id TEXT, archived TEXT, model BLOB, config TEXT)')
                for r in data['archives']:
                    c.execute('INSERT INTO model_archive VALUES (?,?,?,?)',
                              (sid, r['archived'], base64.b64decode(r['model'], validate=True), r['config']))
            if owner:
                c.execute('INSERT INTO auth_workspaces VALUES (?,?)', (sid, owner))
        return {'session_id': sid, 'restored': True, 'message': '已从本浏览器恢复经营数据、执行记录和模型'}
