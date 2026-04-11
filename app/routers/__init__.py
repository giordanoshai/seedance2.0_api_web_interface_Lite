from fastapi import APIRouter
from . import pages, tasks, media, conversations, config

router = APIRouter()

router.include_router(pages.router)
router.include_router(config.router)
router.include_router(conversations.router)
router.include_router(tasks.router)
router.include_router(media.router)
