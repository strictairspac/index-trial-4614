from fastapi import APIRouter,Depends
from src.middlewares.auth import admin
from src.schemas.business import CredentialRotateInput
from src.services import credentials
router=APIRouter()
@router.get('/credentials/status')
def status(u=Depends(admin)):return credentials.status()
@router.post('/credentials/rotate')
def rotate(data:CredentialRotateInput,u=Depends(admin)):
 credentials.safe_url(data)
 return credentials.rotate(data,u)
@router.post('/credentials/retire')
def retire(u=Depends(admin)):return credentials.retire(u)
