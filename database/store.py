import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

def dumps(x): return json.dumps(x,ensure_ascii=False,allow_nan=False)

class Store:
    def __init__(self,path):
        self.path=str(path); Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
                dataset TEXT NOT NULL, metrics TEXT NOT NULL, model BLOB NOT NULL,
                config TEXT NOT NULL, active_decision TEXT);
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                created TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id,created);
            CREATE TABLE IF NOT EXISTS transitions (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                created TEXT NOT NULL, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS company_evidence (id TEXT PRIMARY KEY, company TEXT NOT NULL, record TEXT NOT NULL);
            ''')
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30,check_same_thread=False)
        c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
        finally: c.close()
    def session(self,sid,c=None):
        if c is None:
            with self.connect() as db: return self.session(sid,db)
        row=c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
        if row is None: raise KeyError('会话不存在')
        d=dict(row)
        for k in ['dataset','metrics','config']: d[k]=json.loads(d[k])
        return d
    def decision(self,sid,did,c=None):
        if c is None:
            with self.connect() as db: return self.decision(sid,did,db)
        row=c.execute('SELECT record FROM decisions WHERE id=? AND session_id=?',(did,sid)).fetchone()
        if row is None: raise KeyError('当前会话没有此决策')
        return json.loads(row[0])
    def put_decision(self,sid,record,c):
        c.execute('INSERT INTO decisions(id,session_id,created,status,record) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,record=excluded.record',
                  (record['id'],sid,record['timestamp'],record['status'],dumps(record)))
    def history(self,sid):
        with self.connect() as c:
            rows=c.execute('SELECT record FROM decisions WHERE session_id=? ORDER BY created DESC LIMIT 200',(sid,)).fetchall()
            return [json.loads(x[0]) for x in rows]
    def get_metadata(self,key):
        with self.connect() as c:
            row=c.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
    def set_metadata(self,key,value,c):
        c.execute('INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,dumps(value)))
    def load_company_evidence(self,profile):
        with self.connect() as c:
            for record in profile['records']:
                c.execute('INSERT INTO company_evidence VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET company=excluded.company,record=excluded.record',
                          (record['id'],profile['company'],dumps(record)))
    def company_evidence(self):
        with self.connect() as c:
            return [json.loads(row[0]) for row in c.execute('SELECT record FROM company_evidence ORDER BY id')]
    def retrieve_company_evidence(self,question,limit=3):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        records=self.company_evidence()
        if not records: return []
        texts=[' '.join([r['metric'],r['keywords'],r['note'],r['period']]) for r in records]
        vectors=TfidfVectorizer(analyzer='char',ngram_range=(2,4)).fit_transform(texts+[question])
        scores=cosine_similarity(vectors[-1],vectors[:-1]).ravel()
        indices=sorted(range(len(records)),key=lambda i:(float(scores[i]),records[i]['published']),reverse=True)
        return [{**records[i],'retrieval_score':float(scores[i])} for i in indices[:limit] if scores[i]>0]
