"""SQLAlchemy 基类与会话入口。

引擎不再是进程级单例：账号轮换后存在 active/previous 两代引擎。
- engine：属性，始终返回当前生效账号的引擎，供 API 请求使用
- Session：可调用工厂，每次开一个当前生效账号的会话
- Base：声明式基类，与连接无关，保持不变
- session_for(generation)：worker 试验钉住世代使用
"""
from sqlalchemy.orm import declarative_base
from src.config.credentials import store
Base=declarative_base()
class _EngineProxy:
 def __getattr__(self,name):return getattr(store.active_engine(),name)
engine=_EngineProxy()
def Session():return store.active_session()
def session_for(generation):
 store.engine_for(generation)
 return store._factories[generation]()
def engine_for(generation):return store.engine_for(generation)
