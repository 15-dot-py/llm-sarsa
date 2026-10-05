import os
import httpx
from fastapi import Header,HTTPException

async def cloudbase_user(authorization:str|None=Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"缺少 CloudBase 登录凭证")
    url=os.getenv("CLOUDBASE_TOKEN_INTROSPECT_URL","").strip()
    if not url:
        raise HTTPException(503,"服务器尚未配置 CloudBase Token 校验地址")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response=await client.get(url,headers={"Authorization":authorization})
    except httpx.HTTPError as exc:
        raise HTTPException(503,"CloudBase 身份服务暂时不可用") from exc
    if response.status_code!=200:
        raise HTTPException(401,"CloudBase 登录凭证无效")
    try:
        payload=response.json()
    except ValueError as exc:
        raise HTTPException(503,"CloudBase 身份服务返回异常") from exc
    uid=payload.get("sub")
    if not uid:
        raise HTTPException(401,"CloudBase 登录凭证已失效")
    return str(uid)

def authenticated_session(platform,uid:str):
    with platform.lock:
        with platform.store.connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS authenticated_sessions (
                user_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            row=c.execute("SELECT session_id FROM authenticated_sessions WHERE user_id=?",(uid,)).fetchone()
            if row:
                sid=row["session_id"]
                try:
                    platform.store.session(sid,c)
                    c.execute("UPDATE authenticated_sessions SET updated=CURRENT_TIMESTAMP WHERE user_id=?",(uid,))
                    return {"session_id":sid,"reused":True}
                except KeyError:
                    c.execute("DELETE FROM authenticated_sessions WHERE user_id=?",(uid,))
        created=platform.new_session()
        with platform.store.connect() as c:
            c.execute("""INSERT INTO authenticated_sessions(user_id,session_id)
                         VALUES (?,?)
                         ON CONFLICT(user_id) DO UPDATE SET session_id=excluded.session_id,updated=CURRENT_TIMESTAMP""",
                      (uid,created["session_id"]))
        return {**created,"reused":False}
