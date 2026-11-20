"""数据库账号轮换应用服务：验权、切换、退役与状态查询。"""
from fastapi import HTTPException
from sqlalchemy.engine.url import make_url
from src.config.credentials import store,redact,RotationRejected
from src.services.audit import log
def rotate(data,user):
 target=redact(data.database_url)
 try:
  body=store.rotate(data.database_url)
 except RotationRejected as exc:
  # 验权不过：状态机未动，旧账号保留
  log(user.email,'credential.rotate.rejected',target+' | '+str(exc))
  raise HTTPException(400,str(exc))
 log(user.email,'credential.rotate.applied',f"gen {body['active_generation']} -> {target}")
 return body
def status():return store.status()
def retire(user):
 ok,message=store.retire()
 if not ok:
  log(user.email,'credential.retire.blocked',message)
  raise HTTPException(409,message)
 log(user.email,'credential.retire.done',message)
 return {'retired':True,'message':message,**store.status()}
def safe_url(data):
 # 入口处再校验一次可解析性，避免畸形串进入引擎层
 try:make_url(data.database_url)
 except Exception:raise HTTPException(400,'数据库连接串格式无效')
