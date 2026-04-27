"""
图片服务API路由
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
import io
import zipfile
import time
from pathlib import Path
from typing import List
from pydantic import BaseModel
import logging
import os
import asyncio
import zipfile
import io
import time
from pathlib import Path
import aiohttp

from ..services.image.image_service import get_image_service
from ..services.image.config.image_config import get_image_config, ImageServiceConfig
from ..services.db_config_service import get_db_config_service
from ..services.storage import get_artifact_service
from ..auth.middleware import get_current_user_required
from ..auth.request_context import current_user_id, USER_SCOPE_ALL
from ..database.models import User
from ..utils.thread_pool import run_blocking_io, to_thread

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_image_cache_artifact(image_id: str, user_id: Optional[int] = None):
    return await get_artifact_service().get_task_artifact(
        image_id,
        artifact_type="image_cache",
        user_id=user_id,
    )


async def _stream_artifact_response(artifact, *, attachment: bool = False):
    disposition = "attachment" if attachment else "inline"
    return StreamingResponse(
        get_artifact_service().open_stream(artifact),
        media_type=artifact.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{artifact.filename}"'},
    )


async def _read_artifact_bytes(artifact) -> bytes:
    chunks = []
    async for chunk in get_artifact_service().open_stream(artifact):
        chunks.append(chunk)
    return b"".join(chunks)


class ImageGenerationRequest(BaseModel):
    prompt: str
    provider: Optional[str] = None
    size: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    quality: Optional[str] = None
    style: Optional[str] = None


class ImageTestGenerateRequest(BaseModel):
    provider: Optional[str] = None
    prompt: Optional[str] = None
    size: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    quality: Optional[str] = None
    style: Optional[str] = None


class ImageSuggestionRequest(BaseModel):
    slide_title: str
    slide_content: str
    scenario: str
    topic: str


def _parse_image_dimensions(
    size: Optional[str],
    width: Optional[int],
    height: Optional[int],
    *,
    default_width: int = 1024,
    default_height: int = 1024,
) -> tuple[int, int]:
    """Resolve image dimensions from width/height or a WIDTHxHEIGHT string."""
    try:
        if width and height and int(width) > 0 and int(height) > 0:
            return int(width), int(height)
    except (TypeError, ValueError):
        pass

    if size:
        normalized = str(size).lower().replace("×", "x").strip()
        try:
            parsed_width, parsed_height = [int(part.strip()) for part in normalized.split("x", 1)]
            if parsed_width > 0 and parsed_height > 0:
                return parsed_width, parsed_height
        except (TypeError, ValueError):
            pass

    return default_width, default_height


def _parse_generation_provider(provider_name: Optional[str], *, strict: bool = False):
    from ..services.image.models import ImageProvider

    if provider_name:
        try:
            return ImageProvider(provider_name)
        except ValueError:
            if strict:
                raise HTTPException(status_code=400, detail=f"Unsupported image generation provider: {provider_name}")
            logger.warning("Unsupported image generation provider requested: %s", provider_name)
    return ImageProvider.DALLE


def _get_result_image_url(result) -> Optional[str]:
    if not getattr(result, "image_info", None):
        return None

    from ..services.url_service import build_image_url

    metadata = getattr(result.image_info, "metadata", None)
    return build_image_url(
        result.image_info.image_id,
        width=getattr(metadata, "width", None),
        height=getattr(metadata, "height", None),
    )


def _image_generation_response(result, provider, width: int, height: int) -> Dict[str, Any]:
    image_info = getattr(result, "image_info", None)
    if result.success:
        return {
            "success": True,
            "image_path": _get_result_image_url(result),
            "image_id": image_info.image_id if image_info else None,
            "provider": provider.value if hasattr(provider, "value") else str(provider),
            "width": width,
            "height": height,
            "message": result.message,
        }

    return {
        "success": False,
        "message": result.message,
        "error_code": result.error_code,
        "provider": provider.value if hasattr(provider, "value") else str(provider),
        "width": width,
        "height": height,
    }


@router.get("/api/image/status")
async def get_image_service_status(
    user: User = Depends(get_current_user_required)
):
    """获取图片服务状态"""
    try:
        config_manager = ImageServiceConfig()
        await config_manager.load_config_from_db_async(user.id)
        config = config_manager.get_config()

        db_config_service = get_db_config_service()
        image_settings = await db_config_service.get_config_by_category('image_service', user_id=user.id)
        enable_image_service = image_settings.get('enable_image_service', False)
        enable_local_images = image_settings.get('enable_local_images', False)
        enable_network_search = image_settings.get('enable_network_search', False)
        enable_ai_generation = image_settings.get('enable_ai_generation', False)
        
        # 检查可用的提供者
        available_providers = []

        if enable_local_images:
            available_providers.append('local')

        # 检查DALL-E
        if enable_ai_generation and config.get('dalle', {}).get('api_key'):
            available_providers.append('dalle')

        # 检查Stable Diffusion
        if enable_ai_generation and config.get('stable_diffusion', {}).get('api_key'):
            available_providers.append('stable_diffusion')

        # 检查SiliconFlow
        if enable_ai_generation and config.get('siliconflow', {}).get('api_key'):
            available_providers.append('siliconflow')

        # 检查Gemini图片生成
        if enable_ai_generation and config.get('gemini', {}).get('api_key'):
            available_providers.append('gemini')

        # 检查Pollinations图片生成
        if enable_ai_generation and config.get('pollinations', {}).get('api_key'):
            available_providers.append('pollinations')

        # 检查OpenAI图片生成（自定义端点）
        if enable_ai_generation and config.get('openai_image', {}).get('api_key'):
            available_providers.append('openai_image')
        
        # 检查搜索服务
        search_providers = []
        if enable_network_search:
            if config.get('unsplash', {}).get('api_key'):
                search_providers.append('unsplash')
            if config.get('pixabay', {}).get('api_key'):
                search_providers.append('pixabay')
            if config.get('searxng', {}).get('host'):
                search_providers.append('searxng')

        for provider in search_providers:
            if provider not in available_providers:
                available_providers.append(provider)
        
        # 检查缓存目录
        cache_dir = Path(config.get('cache', {}).get('base_dir', 'temp/images_cache'))
        cache_info = {
            'directory': str(cache_dir),
            'exists': cache_dir.exists(),
            'size': '0 MB',
            'file_count': 0
        }
        
        if cache_dir.exists():
            try:
                files = list(cache_dir.rglob('*'))
                cache_info['file_count'] = len([f for f in files if f.is_file()])
                
                total_size = sum(f.stat().st_size for f in files if f.is_file())
                cache_info['size'] = f"{total_size / (1024 * 1024):.1f} MB"
            except Exception as e:
                logger.warning(f"Failed to get cache info: {e}")
        
        status = "ok" if enable_image_service and available_providers else "no_providers"
        if not enable_image_service:
            status = "disabled"

        return {
            "status": status,
            "available_providers": available_providers,
            "search_providers": search_providers,
            "cache_info": cache_info,
            "message": f"Found {len(available_providers)} image providers and {len(search_providers)} search providers"
        }
        
    except Exception as e:
        logger.error(f"Failed to get image service status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get image service status: {str(e)}")


@router.get("/api/image/pollinations/models")
async def get_pollinations_image_models(
    user: User = Depends(get_current_user_required)
):
    """获取 Pollinations 图片模型列表（/image/models）"""
    try:
        config_manager = ImageServiceConfig()
        await config_manager.load_config_from_db_async(user.id)
        config = (config_manager.get_config() or {}).get('pollinations', {}) or {}

        api_base = (config.get('api_base') or 'https://gen.pollinations.ai').rstrip('/')
        api_key = (config.get('api_key') or '').strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="Pollinations API key not configured")

        url = f"{api_base}/image/models"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers={'Authorization': f'Bearer {api_key}'}) as response:
                if response.status != 200:
                    body = await response.text()
                    raise HTTPException(status_code=502, detail=f"Pollinations API error: HTTP {response.status}: {body}")
                models = await response.json()

        return {
            "success": True,
            "models": models
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch Pollinations image models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch Pollinations image models: {str(e)}")


@router.post("/api/image/test")
async def test_image_service(
    user: User = Depends(get_current_user_required)
):
    """测试图片服务"""
    try:
        image_service = get_image_service()
        image_config = get_image_config()
        config = image_config.get_config()
        
        test_results = {
            "providers": {},
            "cache_info": {}
        }
        
        # 测试DALL-E
        if config.get('dalle', {}).get('api_key'):
            try:
                # 这里可以添加实际的DALL-E测试逻辑
                test_results["providers"]["dalle"] = {
                    "available": True,
                    "message": "DALL-E API密钥已配置"
                }
            except Exception as e:
                test_results["providers"]["dalle"] = {
                    "available": False,
                    "message": f"DALL-E测试失败: {str(e)}"
                }
        else:
            test_results["providers"]["dalle"] = {
                "available": False,
                "message": "DALL-E API密钥未配置"
            }
        
        # 测试Stable Diffusion
        if config.get('stable_diffusion', {}).get('api_key'):
            try:
                test_results["providers"]["stable_diffusion"] = {
                    "available": True,
                    "message": "Stable Diffusion API密钥已配置"
                }
            except Exception as e:
                test_results["providers"]["stable_diffusion"] = {
                    "available": False,
                    "message": f"Stable Diffusion测试失败: {str(e)}"
                }
        else:
            test_results["providers"]["stable_diffusion"] = {
                "available": False,
                "message": "Stable Diffusion API密钥未配置"
            }

        # 测试SiliconFlow
        if config.get('siliconflow', {}).get('api_key'):
            try:
                test_results["providers"]["siliconflow"] = {
                    "available": True,
                    "message": "SiliconFlow API密钥已配置"
                }
            except Exception as e:
                test_results["providers"]["siliconflow"] = {
                    "available": False,
                    "message": f"SiliconFlow测试失败: {str(e)}"
                }
        else:
            test_results["providers"]["siliconflow"] = {
                "available": False,
                "message": "SiliconFlow API密钥未配置"
            }

        # 测试Pollinations
        if config.get('pollinations', {}).get('api_key'):
            try:
                test_results["providers"]["pollinations"] = {
                    "available": True,
                    "message": "Pollinations API密钥已配置"
                }
            except Exception as e:
                test_results["providers"]["pollinations"] = {
                    "available": False,
                    "message": f"Pollinations测试失败: {str(e)}"
                }
        else:
            test_results["providers"]["pollinations"] = {
                "available": False,
                "message": "Pollinations API密钥未配置"
            }


        # 测试缓存
        cache_dir = Path(config.get('cache', {}).get('base_dir', 'temp/images_cache'))
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            files = list(cache_dir.rglob('*'))
            file_count = len([f for f in files if f.is_file()])
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            
            test_results["cache_info"] = {
                "directory": str(cache_dir),
                "file_count": file_count,
                "size": f"{total_size / (1024 * 1024):.1f} MB",
                "writable": os.access(cache_dir, os.W_OK)
            }
        except Exception as e:
            test_results["cache_info"] = {
                "directory": str(cache_dir),
                "error": f"缓存目录测试失败: {str(e)}"
            }
        
        return test_results
        
    except Exception as e:
        logger.error(f"Image service test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image service test failed: {str(e)}")


@router.post("/api/image/test-generate")
async def test_generate_image(
    request: ImageTestGenerateRequest,
    user: User = Depends(get_current_user_required),
):
    """生成一张测试图片，用于验证当前用户的图片生成配置。"""
    try:
        db_config_service = get_db_config_service()
        image_settings = await db_config_service.get_config_by_category('image_service', user_id=user.id)

        if not image_settings.get('enable_image_service'):
            raise HTTPException(status_code=400, detail="图片服务未启用")
        if not image_settings.get('enable_ai_generation'):
            raise HTTPException(status_code=400, detail="AI图片生成未启用")

        provider_name = request.provider or image_settings.get('default_ai_image_provider') or 'dalle'
        provider = _parse_generation_provider(provider_name, strict=True)

        config_manager = ImageServiceConfig()
        await config_manager.load_config_from_db_async(user.id)
        config = config_manager.get_config() or {}
        provider_config = config.get(provider.value, {}) or {}

        api_key = provider_config.get('api_key')
        if api_key is not None and not str(api_key).strip():
            raise HTTPException(status_code=400, detail=f"{provider.value} API key not configured")

        default_width, default_height = _parse_image_dimensions(
            provider_config.get('default_size'),
            provider_config.get('default_width'),
            provider_config.get('default_height'),
        )
        width, height = _parse_image_dimensions(
            request.size,
            request.width,
            request.height,
            default_width=default_width,
            default_height=default_height,
        )

        prompt = (
            request.prompt
            or "A clean modern presentation test image, abstract business technology background, high quality"
        )

        from ..services.image.models import ImageGenerationRequest as ServiceImageGenerationRequest

        service_request = ServiceImageGenerationRequest(
            prompt=prompt,
            provider=provider,
            width=width,
            height=height,
            quality=request.quality or provider_config.get('default_quality') or "standard",
            style=request.style or provider_config.get('default_style'),
        )

        image_service = get_image_service()
        await image_service.reload_providers_for_user(user.id)
        result = await image_service.generate_image(service_request)

        response = _image_generation_response(result, provider, width, height)
        response["prompt"] = prompt
        if not result.success:
            return response
        response["message"] = result.message or "测试图片生成成功"
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Test image generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Test image generation failed: {str(e)}")


@router.post("/api/image/cache/clear")
async def clear_image_cache(
    user: User = Depends(get_current_user_required)
):
    """清理图片缓存"""
    try:
        image_config = get_image_config()
        config = image_config.get_config()

        cache_dir = Path(config.get('cache', {}).get('base_dir', 'temp/images_cache'))

        if not cache_dir.exists():
            return {
                "success": True,
                "deleted_files": 0,
                "freed_space": "0 MB",
                "message": "缓存目录不存在"
            }

        # 在线程池中执行文件删除操作
        result = await run_blocking_io(_clear_cache_sync, cache_dir)

        return {
            "success": True,
            "deleted_files": result["deleted_count"],
            "freed_space": f"{result['freed_space_mb']:.1f} MB",
            "message": f"成功清理了 {result['deleted_count']} 个文件"
        }

    except Exception as e:
        logger.error(f"Failed to clear image cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear image cache: {str(e)}")


def _clear_cache_sync(cache_dir: Path) -> Dict[str, Any]:
    """同步清理缓存（在线程池中运行）"""
    # 统计删除前的信息
    files = list(cache_dir.rglob('*'))
    files_to_delete = [f for f in files if f.is_file()]
    total_size_before = sum(f.stat().st_size for f in files_to_delete)

    # 删除文件
    deleted_count = 0
    for file_path in files_to_delete:
        try:
            file_path.unlink()
            deleted_count += 1
        except Exception as e:
            logger.warning(f"Failed to delete {file_path}: {e}")

    # 删除空目录
    for dir_path in sorted([f for f in files if f.is_dir()], reverse=True):
        try:
            if not any(dir_path.iterdir()):  # 如果目录为空
                dir_path.rmdir()
        except Exception as e:
            logger.warning(f"Failed to remove directory {dir_path}: {e}")

    freed_space_mb = total_size_before / (1024 * 1024)

    return {
        "deleted_count": deleted_count,
        "freed_space_mb": freed_space_mb
    }


@router.post("/api/image/generate")
async def generate_image(
    request: ImageGenerationRequest,
    user: User = Depends(get_current_user_required)
):
    """生成图片"""
    try:
        image_service = get_image_service()
        # Ensure per-user provider keys (DB) are loaded before generating.
        await image_service.reload_providers_for_user(user.id)

        from ..services.image.models import ImageGenerationRequest as ServiceImageGenerationRequest

        width, height = _parse_image_dimensions(request.size, request.width, request.height)
        provider = _parse_generation_provider(request.provider)

        service_request = ServiceImageGenerationRequest(
            prompt=request.prompt,
            provider=provider,
            width=width,
            height=height,
            quality=request.quality or "standard",
            style=request.style
        )

        # 生成图片
        result = await image_service.generate_image(service_request)

        return _image_generation_response(result, provider, width, height)

    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


@router.post("/api/image/suggest")
async def suggest_images(
    request: ImageSuggestionRequest,
    user: User = Depends(get_current_user_required)
):
    """为幻灯片建议图片"""
    try:
        image_service = get_image_service()

        # 获取图片建议
        suggestions = await image_service.suggest_images_for_ppt_slide(
            slide_title=request.slide_title,
            slide_content=request.slide_content,
            scenario=request.scenario,
            topic=request.topic
        )
        
        return {
            "success": True,
            "suggestions": suggestions,
            "message": "图片建议生成成功"
        }
        
    except Exception as e:
        logger.error(f"Image suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image suggestion failed: {str(e)}")


# 图库管理API
@router.get("/api/image/gallery/stats")
async def get_gallery_stats(
    user: User = Depends(get_current_user_required)
):
    """获取图库统计信息"""
    try:
        image_service = get_image_service()
        stats = await image_service.get_cache_stats()

        # 按来源分类统计
        cache_stats = {
            'ai_generated': 0,
            'web_search': 0,
            'local_storage': 0,
            'cache_size': '0 MB'
        }

        if 'categories' in stats:
            for category, count in stats['categories'].items():
                if category in cache_stats:
                    cache_stats[category] = count

        if 'total_size_mb' in stats:
            cache_stats['cache_size'] = f"{stats['total_size_mb']:.1f} MB"

        return {
            "success": True,
            "stats": cache_stats
        }

    except Exception as e:
        logger.error(f"Failed to get gallery stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get gallery stats: {str(e)}")


@router.get("/api/image/gallery/list")
async def list_gallery_images(
    page: int = 1,
    per_page: int = 20,
    category: str = "",
    search: str = "",
    sort: str = "created_desc",
    user: User = Depends(get_current_user_required)
):
    """获取图库图片列表"""
    try:
        image_service = get_image_service()

        # 构建搜索参数
        search_params = {
            'page': page,
            'per_page': per_page,
            'category': category if category else None,
            'search': search if search else None,
            'sort': sort
        }

        # 获取图片列表（这里需要实现相应的服务方法）
        result = await image_service.list_cached_images(**search_params)

        return {
            "success": True,
            "images": result['images'],
            "pagination": {
                "current_page": page,
                "per_page": per_page,
                "total_count": result['total_count'],
                "total_pages": (result['total_count'] + per_page - 1) // per_page,
                "has_prev": page > 1,
                "has_next": page * per_page < result['total_count']
            }
        }

    except Exception as e:
        logger.error(f"Failed to list gallery images: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list gallery images: {str(e)}")


@router.get("/api/image/detail/{image_id}")
async def get_image_detail(
    image_id: str,
    user: User = Depends(get_current_user_required)
):
    """获取图片详细信息"""
    try:
        image_service = get_image_service()
        image_info = await image_service.get_image(image_id)

        if not image_info:
            raise HTTPException(status_code=404, detail="Image not found")

        return {
            "success": True,
            "image": {
                "image_id": image_info.image_id,
                "title": image_info.title,
                "description": image_info.description,
                "tags": ','.join([tag.name for tag in image_info.tags]) if image_info.tags else '',
                "category": image_info.source_type.value,
                "filename": image_info.filename,
                "file_size": image_info.metadata.file_size,
                "width": image_info.metadata.width,
                "height": image_info.metadata.height,
                "format": image_info.metadata.format.value,
                "source_type": image_info.source_type.value,
                "provider": image_info.provider.value,
                "created_at": image_info.created_at,
                "access_count": getattr(image_info, 'access_count', 0)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get image detail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get image detail: {str(e)}")


@router.get("/api/image/{image_id}/info")
async def get_image_info(
    image_id: str,
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """获取图片信息，包括绝对URL"""
    try:
        image_service = get_image_service()
        image_info = await image_service.get_image(image_id)

        if not image_info:
            raise HTTPException(status_code=404, detail="Image not found")

        # 构建绝对URL
        from ..services.url_service import build_image_url
        absolute_url = build_image_url(
            image_id,
            width=image_info.metadata.width,
            height=image_info.metadata.height,
        )

        return {
            "success": True,
            "image_info": {
                "image_id": image_info.image_id,
                "title": image_info.title,
                "filename": image_info.filename,
                "absolute_url": absolute_url,
                "file_size": image_info.metadata.file_size,
                "width": image_info.metadata.width,
                "height": image_info.metadata.height,
                "format": image_info.metadata.format.value,
                "source_type": image_info.source_type.value,
                "provider": image_info.provider.value,
                "created_at": image_info.created_at
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get image info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get image info: {str(e)}")


@router.get("/api/image/view/{image_id}")
async def view_image(
    image_id: str
):
    """查看图片"""
    try:
        artifact = await _get_image_cache_artifact(image_id)
        if artifact:
            return await _stream_artifact_response(artifact)

        image_service = get_image_service()
        image_info = await image_service.get_image(image_id)

        if not image_info or not image_info.local_path:
            raise HTTPException(status_code=404, detail="Image not found")

        image_path = Path(image_info.local_path)
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image file not found")

        return FileResponse(
            path=str(image_path),
            media_type=f"image/{image_info.metadata.format.value}",
            filename=image_info.filename
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to view image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to view image: {str(e)}")


@router.get("/api/image/thumbnail/{image_id}")
async def get_image_thumbnail(
    image_id: str
):
    """获取图片缩略图"""
    try:
        image_service = get_image_service()

        # 尝试获取缩略图
        thumbnail_path = await image_service.get_thumbnail(image_id)

        if thumbnail_path and Path(thumbnail_path).exists():
            return FileResponse(
                path=str(thumbnail_path),
                media_type="image/jpeg"
            )

        # 如果没有缩略图，返回原图 artifact/S3 对象
        artifact = await _get_image_cache_artifact(image_id)
        if artifact:
            return await _stream_artifact_response(artifact)

        image_info = await image_service.get_image(image_id)
        if image_info and image_info.local_path and Path(image_info.local_path).exists():
            return FileResponse(
                path=str(image_info.local_path),
                media_type=f"image/{image_info.metadata.format.value}"
            )

        raise HTTPException(status_code=404, detail="Thumbnail not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get thumbnail: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get thumbnail: {str(e)}")


@router.get("/api/image/download/{image_id}")
async def download_image(
    image_id: str,
    user: User = Depends(get_current_user_required)
):
    """下载单张图片"""
    try:
        image_service = get_image_service()
        image_info = await image_service.get_image(image_id)

        artifact = await _get_image_cache_artifact(image_id, user_id=user.id)
        if artifact:
            return await _stream_artifact_response(artifact, attachment=True)

        if not image_info or not image_info.local_path:
            raise HTTPException(status_code=404, detail="Image not found")

        image_path = Path(image_info.local_path)
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image file not found")

        return FileResponse(
            path=str(image_path),
            media_type=f"image/{image_info.metadata.format.value}",
            filename=image_info.filename,
            headers={"Content-Disposition": f"attachment; filename=\"{image_info.filename}\""}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download image: {str(e)}")


class BatchDeleteRequest(BaseModel):
    image_ids: List[str]


class BatchDownloadRequest(BaseModel):
    image_ids: List[str]


@router.delete("/api/image/delete/{image_id}")
async def delete_single_image(
    image_id: str,
    user: User = Depends(get_current_user_required)
):
    """删除单张图片"""
    try:
        image_service = get_image_service()

        # 删除图片
        result = await image_service.delete_image(image_id)

        if result:
            return {
                "success": True,
                "message": "图片删除成功"
            }
        else:
            raise HTTPException(status_code=404, detail="Image not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")


@router.post("/api/image/gallery/batch-delete")
async def batch_delete_images(
    request: BatchDeleteRequest,
    user: User = Depends(get_current_user_required)
):
    """批量删除图片"""
    try:
        image_service = get_image_service()

        deleted_count = 0
        failed_ids = []

        for image_id in request.image_ids:
            try:
                result = await image_service.delete_image(image_id)
                if result:
                    deleted_count += 1
                else:
                    failed_ids.append(image_id)
            except Exception as e:
                logger.warning(f"Failed to delete image {image_id}: {e}")
                failed_ids.append(image_id)

        return {
            "success": True,
            "deleted_count": deleted_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids,
            "message": f"成功删除 {deleted_count} 张图片"
        }

    except Exception as e:
        logger.error(f"Batch delete failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


@router.post("/api/image/gallery/batch-download")
async def batch_download_images(
    request: BatchDownloadRequest,
    user: User = Depends(get_current_user_required)
):
    """批量下载图片"""
    try:
        image_service = get_image_service()

        # 获取所有图片信息
        zip_buffer = io.BytesIO()
        added_count = 0
        used_names = set()
        artifact_service = get_artifact_service()

        def safe_zip_name(name: str, fallback: str) -> str:
            candidate = os.path.basename(name or fallback) or fallback
            stem, ext = os.path.splitext(candidate)
            unique = candidate
            index = 2
            while unique in used_names:
                unique = f"{stem}-{index}{ext}"
                index += 1
            used_names.add(unique)
            return unique

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for image_id in request.image_ids:
                try:
                    artifact = await artifact_service.get_task_artifact(image_id, artifact_type="image_cache", user_id=user.id)
                    if artifact:
                        zip_file.writestr(safe_zip_name(artifact.filename, image_id), await _read_artifact_bytes(artifact))
                        added_count += 1
                        continue

                    image_info = await image_service.get_image(image_id)
                    if image_info and image_info.local_path:
                        image_path = Path(image_info.local_path)
                        if image_path.exists():
                            zip_file.write(str(image_path), safe_zip_name(image_info.filename, image_path.name))
                            added_count += 1
                except Exception as e:
                    logger.warning(f"Failed to get image {image_id}: {e}")
                    continue

        if added_count == 0:
            raise HTTPException(status_code=404, detail="No downloadable images found")

        zip_buffer.seek(0)
        timestamp = int(time.time())
        filename = f"images_{timestamp}.zip"

        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )

    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch download failed: {str(e)}")


def _create_zip_sync(image_infos: List[Dict[str, str]]) -> bytes:
    """同步创建ZIP文件（在线程池中运行）"""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for image_info in image_infos:
            try:
                zip_file.write(image_info['path'], image_info['filename'])
            except Exception as e:
                logger.warning(f"Failed to add {image_info['filename']} to zip: {e}")
                continue

    zip_buffer.seek(0)
    return zip_buffer.read()


@router.post("/api/image/upload")
async def upload_image(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form("local_storage"),
    tags: str = Form(""),
    user: User = Depends(get_current_user_required)
):
    """上传图片"""
    try:
        # 验证文件类型
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Invalid file type")

        # 在线程池中读取文件数据
        file_data = await file.read()

        # 创建上传请求
        from ..services.image.models import ImageUploadRequest
        upload_request = ImageUploadRequest(
            filename=file.filename,
            file_size=len(file_data),
            title=title if title else file.filename.split('.')[0],
            description=description,
            category=category,
            tags=[tag.strip() for tag in tags.split(',') if tag.strip()] if tags else [],
            content_type=file.content_type
        )

        # 上传图片
        image_service = get_image_service()
        result = await image_service.upload_image(upload_request, file_data)

        if result.success:
            return {
                "success": True,
                "image_id": result.image_info.image_id,
                "message": "图片上传成功"
            }
        else:
            raise HTTPException(status_code=400, detail=result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")


class ImageUpdateRequest(BaseModel):
    """图片信息更新请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None
    category: Optional[str] = None


@router.put("/api/image/{image_id}/update")
async def update_image_info(
    image_id: str,
    request: ImageUpdateRequest,
    user: User = Depends(get_current_user_required)
):
    """更新图片信息"""
    try:
        image_service = get_image_service()
        image_info = await image_service.get_image(image_id)

        if not image_info:
            raise HTTPException(status_code=404, detail="Image not found")

        # 更新图片信息
        if request.title is not None:
            image_info.title = request.title

        if request.description is not None:
            image_info.description = request.description

        if request.tags is not None:
            # 清除现有标签
            image_info.tags = []
            # 添加新标签
            if request.tags.strip():
                tag_names = [tag.strip() for tag in request.tags.split(',') if tag.strip()]
                for tag_name in tag_names:
                    image_info.add_tag(tag_name)

        if request.category is not None:
            # 更新分类（通过source_type）
            from ..services.image.models import ImageSourceType
            try:
                image_info.source_type = ImageSourceType(request.category)
            except ValueError:
                # 如果分类无效，保持原有分类
                pass

        # 更新时间戳
        import time
        image_info.updated_at = time.time()

        # 保存更新后的图片信息
        # 通过重新保存元数据来更新信息
        cache_key = image_service.cache_manager._generate_cache_key(image_info)
        await image_service.cache_manager._save_image_metadata(cache_key, image_info)

        return {
            "success": True,
            "message": "图片信息已更新",
            "image": {
                "image_id": image_info.image_id,
                "title": image_info.title,
                "description": image_info.description,
                "tags": ','.join([tag.name for tag in image_info.tags]) if image_info.tags else '',
                "category": image_info.source_type.value
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update image info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update image info: {str(e)}")


@router.post("/api/image/gallery/deduplicate")
async def deduplicate_gallery(
    user: User = Depends(get_current_user_required)
):
    """去重图库中的重复图片"""
    try:
        image_service = get_image_service()

        # 执行去重操作
        result = await image_service.deduplicate_cache()

        return {
            "success": True,
            "message": f"已去重 {result['duplicates_removed']} 张重复图片",
            "duplicates_removed": result['duplicates_removed']
        }

    except Exception as e:
        logger.error(f"Failed to deduplicate gallery: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to deduplicate gallery: {str(e)}")


@router.post("/api/image/gallery/clear-all")
async def clear_all_images(
    user: User = Depends(get_current_user_required)
):
    """清空当前用户图床；仅管理员可显式触发全局清空。"""
    try:
        image_service = get_image_service()
        is_global_clear = bool(
            getattr(user, "is_admin", False) and current_user_id.get() == USER_SCOPE_ALL
        )

        # 获取当前作用域内的图片统计信息
        stats = await image_service.get_cache_stats()
        total_images = stats.get('total_entries', 0)

        if total_images == 0:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "图库已经是空的" if is_global_clear else "你的图库已经是空的"
            }

        # 普通用户只能清空自己的图库；全局清空仅保留给显式 admin/system 作用域。
        if is_global_clear:
            deleted_count = await image_service.clear_all_cache()
            message = f"成功清空全局图库，删除了 {deleted_count} 张图片"
        else:
            deleted_count = await image_service.clear_user_cache(user.id)
            message = f"成功清空你的图库，删除了 {deleted_count} 张图片"

        return {
            "success": True,
            "deleted_count": deleted_count,
            "message": message
        }

    except Exception as e:
        logger.error(f"Failed to clear all images: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear all images: {str(e)}")
