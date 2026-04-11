from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/template")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """返回主页面"""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "storage_bucket": settings.STORAGE_BUCKET,
            "thumbnail_bucket": settings.THUMBNAIL_BUCKET,
        }
    )
