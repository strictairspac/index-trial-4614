import time,logging
from pathlib import Path
import redis
from src.config.settings import REDIS_URL
from src.config.database import session_for,engine_for
from src.config.credentials import store
# 导入全部模型以注册完整表关系（Experiment 外键依赖 workloads/candidates 表）
from src.models.workload import Workload
from src.models.candidate import Candidate
from src.models.experiment import Experiment
from src.services.index_algorithm import run
from src.services.audit import log
q=redis.Redis.from_url(REDIS_URL)
def _set_status(run_id,generation,status,**changes):
 with session_for(generation) as s:
  row=s.get(Experiment,run_id)
  if not row:return None
  row.status=status
  for k,v in changes.items():setattr(row,k,v)
  s.commit();s.refresh(row);return row.snapshot
def main():
 # 重启恢复：已到终态的试验退出在跑名册，并尝试回收上一代引擎
 store.reconcile_runs();store.auto_retire()
 while True:
  Path('/tmp/worker-heartbeat').touch()
  try:
   item=q.blpop('index-trials',timeout=2)
   if not item:
    # 空闲时同步轮换状态并回收本地过期世代引擎
    store.refresh();continue
   run_id=int(item[1])
   # 钉住开工时刻的生效账号：在跑试验全程沿用该账号，不受后续轮换影响
   generation=store.register_run(run_id)
   try:
    with session_for(generation) as s:
     row=s.get(Experiment,run_id)
     if not row or row.status!='queued':continue
     snapshot=row.snapshot;row.status='running';s.commit()
    try:
     result=run(snapshot,engine_for(generation))
     _set_status(run_id,generation,'completed',result=result)
     log('worker','experiment.completed',str(run_id))
    except Exception as exc:
     logging.exception('trial failed')
     _set_status(run_id,generation,'failed',error=str(exc)[:1000])
   finally:
    store.unregister_run(generation,run_id)
    # 旧试验清理完后，若旧连接也全部归还，自动退役旧账号引擎
    store.auto_retire()
  except Exception:
   logging.exception('worker loop');time.sleep(2)
if __name__=='__main__':main()
