"""数据库账号轮换状态机。

两代账号模型：active 承载切换后的全部新请求与新试验；previous 保留给
切换瞬间仍在跑的试验，直到它们清理完索引、保存成绩。状态（含连接串）
持久化在 Redis，服务重启后继续使用已生效的账号。对外状态一律脱敏，
绝不暴露密码。
"""
import logging, threading, os, uuid
import redis
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from src.config.settings import DATABASE_URL, REDIS_URL

STATE_KEY='credential:state'
RUNS_PREFIX='credential:runs:'
CONNS_PREFIX='credential:conns:'
CONNS_TTL=90
TERMINAL_STATUSES=('completed','failed')
INSTANCE_ID=f'{os.getpid()}-{uuid.uuid4().hex[:8]}'
# 数据库不可达时快速失败，避免轮换验权与请求无限挂起
CONNECT_ARGS={'connect_timeout':10,'read_timeout':30,'write_timeout':30}

def redact(url):
 """剥除密码，仅保留 user@host:port/db 供展示与审计。"""
 u=make_url(url).set(password=None)
 return str(u)

class RotationRejected(RuntimeError):
 """新账号验权失败等原因导致轮换被拒绝，旧账号保持不变。"""

class CredentialStore:
 def __init__(self,redis_url):
  self.r=redis.Redis.from_url(redis_url)
  self._lock=threading.RLock()
  self._engines={}
  self._factories={}
  self._checkouts={}
  self._load()
  # 兜底心跳：长连接无 checkout/checkin 事件时也定期续期，避免被 TTL 误判为僵尸
  self._heartbeat=threading.Thread(target=self._heartbeat_loop,name='cred-heartbeat',daemon=True)
  self._heartbeat.start()

 def _heartbeat_loop(self):
  while True:
   try:self._report_connections()
   except Exception:logging.exception('heartbeat failed')
   threading.Event().wait(CONNS_TTL//3)

 def _load(self):
  data=self.r.hgetall(STATE_KEY)
  data={k.decode():v.decode() for k,v in data.items()}
  if not data:
   data={'active_url':DATABASE_URL,'active_generation':'1','previous_url':'','previous_generation':'','rotated_at':'','retired_at':'','version':'1'}
   self.r.hset(STATE_KEY,mapping=data)
  self._state=data

 def refresh(self):
  """从 Redis 重新加载轮换状态（API 与 worker 是不同进程），
  并回收本地已不在 active/previous 名册中的世代引擎。"""
  with self._lock:
   self._load()
   live={self.active_generation}
   if self.previous_generation is not None:live.add(self.previous_generation)
   for gen in [g for g in self._engines if g not in live]:
    try:self._engines[gen].dispose()
    except Exception:logging.exception('dispose stale generation %s',gen)
    self._engines.pop(gen,None);self._factories.pop(gen,None);self._checkouts.pop(gen,None)
   self._report_connections()
  return self

 def _persist(self,**changes):
  self._state.update(changes)
  self.r.hset(STATE_KEY,mapping=changes)

 @property
 def active_generation(self):return int(self._state['active_generation'])
 @property
 def previous_generation(self):return int(self._state['previous_generation']) if self._state.get('previous_generation') else None
 @property
 def active_url(self):return self._state['active_url']
 @property
 def previous_url(self):return self._state.get('previous_url') or ''

 def _make_engine(self,url,generation):
  engine=create_engine(url,pool_pre_ping=True,connect_args=CONNECT_ARGS)
  counters={'checkouts':0}
  # 借还连接即时上报：长试验（如阻塞等 GET_LOCK）期间 refresh 不运行，
  # 靠事件保证该进程持有的旧账号连接在集群视图中始终可见
  @event.listens_for(engine,'checkout')
  def _checkout(dbapi_conn,record,proxy):
   counters['checkouts']+=1;self._report_connections()
  @event.listens_for(engine,'checkin')
  def _checkin(dbapi_conn,record):
   counters['checkouts']-=1;self._report_connections()
  self._engines[generation]=engine
  self._factories[generation]=sessionmaker(bind=engine)
  self._checkouts[generation]=counters
  return engine

 def engine_for(self,generation):
  with self._lock:
   if generation in self._engines:return self._engines[generation]
   url=self.active_url if generation==self.active_generation else self.previous_url
   if not url:raise RotationRejected(f'世代 {generation} 的账号已退役，无法建立连接')
   return self._make_engine(url,generation)

 def active_engine(self):return self.engine_for(self.active_generation)
 def active_session(self):
  gen=self.active_generation
  if gen not in self._factories:self.engine_for(gen)
  return self._factories[gen]()

 def verify(self,url):
  """用候选账号真实连库验权：先 SELECT 1 验证登录，再探目标库表权限。"""
  engine=create_engine(url,pool_pre_ping=True,connect_args=CONNECT_ARGS)
  try:
   with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
    conn.execute(text('SELECT 1 FROM telemetry LIMIT 1'))
    return True
  except SQLAlchemyError as exc:
   raise RotationRejected('新账号连库验权失败：'+str(exc.orig if getattr(exc,'orig',None) else exc).split('\n')[0])
  finally:
   engine.dispose()

 def rotate(self,url):
  """验权通过才切换；失败抛 RotationRejected，旧账号原样保留。"""
  with self._lock:
   if make_url(url).render_as_string(hide_password=False)==self.active_url:
    raise RotationRejected('候选账号与当前生效账号相同，无需轮换')
   self.verify(url)
   prev_gen=self.active_generation
   new_gen=prev_gen+1
   self._make_engine(url,new_gen)
   self._persist(previous_url=self.active_url,previous_generation=str(prev_gen),
    active_url=url,active_generation=str(new_gen),
    version=str(int(self._state['version'])+1),rotated_at=_now(),retired_at='')
   return self.status()

 def register_run(self,experiment_id):
  """试验开工时钉住当前世代，返回世代号；全程只允许用该世代引擎。"""
  self.refresh()
  generation=self.active_generation
  self.r.sadd(RUNS_PREFIX+str(generation),experiment_id)
  return generation

 def unregister_run(self,generation,experiment_id):
  self.r.srem(RUNS_PREFIX+str(generation),experiment_id)

 def runs_for(self,generation):
  return sorted(int(x) for x in self.r.smembers(RUNS_PREFIX+str(generation)))

 def _report_connections(self):
  """把本进程各世代借出连接数心跳到 Redis，TTL 兜底僵尸进程。"""
  payload={str(g):str(c['checkouts']) for g,c in self._checkouts.items()}
  key=CONNS_PREFIX+INSTANCE_ID
  try:
   if payload:
    self.r.hset(key,mapping=payload);self.r.expire(key,CONNS_TTL)
   else:self.r.delete(key)
  except redis.RedisError:logging.exception('report connections failed')

 def cluster_open_connections(self,generation):
  """汇总所有存活进程在指定世代上的借出连接数。"""
  total=0
  for key in self.r.scan_iter(CONNS_PREFIX+'*'):
   raw=self.r.hget(key,str(generation))
   if raw:total+=int(raw)
  return total

 def reconcile_runs(self):
  """重启恢复或退役前，把已经到终态的试验从在跑名册移除。"""
  self.refresh()
  from src.config.database import Session
  from src.models.experiment import Experiment
  for key in self.r.scan_iter(RUNS_PREFIX+'*'):
   generation=int(key.decode().removeprefix(RUNS_PREFIX))
   ids=sorted(int(x) for x in self.r.smembers(key))
   if not ids:continue
   with Session() as s:
    done={x[0] for x in s.query(Experiment.id).filter(Experiment.id.in_(ids),Experiment.status.in_(TERMINAL_STATUSES)).all()}
   if done:self.r.srem(key,*done)

 def can_retire(self):
  prev=self.previous_generation
  if prev is None:return False,'没有待退役的旧账号'
  self.reconcile_runs()
  running=self.runs_for(prev)
  if running:return False,f'旧账号仍有 {len(running)} 个试验未清理（试验 {running}）'
  # 汇总 API 与 worker 等全部存活进程的旧账号连接，任一进程仍持有即不可撤
  open_conn=self.cluster_open_connections(prev)
  if open_conn:return False,f'旧账号仍有 {open_conn} 个连接未退出'
  return True,''

 def retire(self):
  """条件满足才关闭旧引擎（连接全部归还池并 dispose），返回是否成功。"""
  with self._lock:
   self.refresh()
   ok,reason=self.can_retire()
   if not ok:return False,reason
   prev=self.previous_generation
   # 本进程可能从未构建过该世代引擎（例如重启后没有旧试验落在本进程），
   # 此时本地无连接需要回收，仅清理状态即可
   if prev in self._engines:
    self._engines[prev].dispose()
   self._engines.pop(prev,None);self._factories.pop(prev,None);self._checkouts.pop(prev,None)
   self.r.delete(RUNS_PREFIX+str(prev))
   self._report_connections()
   self._persist(previous_url='',previous_generation='',retired_at=_now())
   return True,'旧账号连接已全部退出，账号可撤'

 def auto_retire(self):
  try:
   self.refresh()
   if self.previous_generation is not None:self.retire()
  except Exception:logging.exception('auto retire failed')

 def status(self):
  self.refresh()
  prev=self.previous_generation
  body={'active_generation':self.active_generation,
        'active_account':redact(self.active_url),
        'rotated_at':self._state.get('rotated_at') or None,
        'version':int(self._state['version']),
        'previous_present':prev is not None,
        'retired_at':self._state.get('retired_at') or None}
  if prev is not None:
   running=self.runs_for(prev)
   revocable,_=self.can_retire()
   body.update(previous_generation=prev,previous_account=redact(self.previous_url),
    previous_running_experiments=running,
    previous_open_connections=self.cluster_open_connections(prev),
    previous_revocable=revocable)
  self._report_connections()
  return body

def _now():
 from datetime import datetime,timezone
 return datetime.now(timezone.utc).isoformat(timespec='seconds')

store=CredentialStore(REDIS_URL)
