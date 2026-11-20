import os,logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from src.config.database import engine
from src.config.credentials import store
from src.services.experiments import queue
from src.routes import auth,workloads,candidates,experiments,audit,credentials
from src.middlewares.errors import install_errors
from src.middlewares.requests import RequestTrace
@asynccontextmanager
async def lifespan(app):
 # 重启恢复：继续使用 Redis 中已生效的账号；清理终态名册并尝试回收旧引擎
 store.reconcile_runs();store.auto_retire()
 if os.getenv('SEED_DEMO','true').lower()=='true':
  try:
   from scripts.seed_demo import seed
   seed()
  except Exception:logging.exception('seed failed; API remains available')
 yield
app=FastAPI(title='岩川 · 设备遥测索引试验室',lifespan=lifespan)
app.add_middleware(RequestTrace);install_errors(app)
for r in (auth,workloads,candidates,experiments,audit,credentials):app.include_router(r.router)
@app.get('/health')
def health():
 with engine.connect() as c:c.execute(text('SELECT 1'))
 queue.ping();return {'status':'ok'}
