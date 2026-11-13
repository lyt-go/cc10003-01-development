"""口径影响面接口：指标卡预览、口径版本发布、引用影响面与审计查询。

顺着「指标定义 → 口径版本 → 看板指标卡」的数据流组织：
- GET  /api/metricgov/panel                     面板总览（指标、卡片、待重算、已阻止）
- GET  /api/metricgov/metrics/{code}/profile    单个指标的当前口径与引用看板
- GET  /api/metricgov/metrics/{code}/versions   口径版本历史（含已发布历史版本追溯）
- POST /api/metricgov/metrics/{code}/preview    发布前预览影响面
- POST /api/metricgov/metrics/{code}/publish    发布新口径版本（同一提交原子生效）
- POST /api/metricgov/cards/{code}/refresh      刷新单张指标卡（未发布指标明确阻止）
- GET  /api/metricgov/cards                     指标卡清单
- GET  /api/metricgov/releases                  看板发布记录
- GET  /api/metricgov/audits                    审计记录
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.schemas import ActionResult, EntryPayload
from app.services.metricgov import MetricgovService

router = APIRouter(prefix="/api/metricgov", tags=["口径影响面"])

service = MetricgovService()


@router.get("/panel", response_model=dict)
def panel() -> dict[str, Any]:
    """面板总览：指标当前版本、统计粒度、时间窗口与卡片处理状态汇总。"""
    return service.panel()


@router.get("/metrics/{metric_code}/profile", response_model=dict)
def metric_profile(metric_code: str) -> dict[str, Any]:
    """单个指标的口径档案：当前版本、统计粒度、时间窗口、引用它的看板页面。"""
    profile = service.metric_profile(metric_code)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"指标定义 {metric_code} 不存在或已归档")
    return profile


@router.get("/metrics/{metric_code}/versions", response_model=dict)
def metric_versions(metric_code: str) -> dict[str, Any]:
    """口径版本历史：当前版本在前，已发布的历史版本仍可按当时口径追溯。"""
    return {"items": service.versions(metric_code)}


@router.post("/metrics/{metric_code}/preview", response_model=ActionResult)
def preview(metric_code: str, payload: EntryPayload) -> ActionResult:
    """发布前预览：区分公式变化、筛选变化、仅名称变化造成的不同影响。"""
    result, message = service.preview(metric_code, payload.values)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=result["提示"], entry=result)


@router.post("/metrics/{metric_code}/publish", response_model=ActionResult)
def publish(metric_code: str, payload: EntryPayload) -> ActionResult:
    """发布新口径版本：只让受影响的指标卡待重算，其余复用原结果。

    并发发布同一条指标时按基准版本校验，失败一侧不留半套引用。
    """
    values = payload.values
    result, message = service.publish(
        metric_code,
        values,
        base_version=str(values.get("基准版本") or ""),
        dashboard_code=str(values.get("发起看板") or ""),
        operator=str(values.get("操作人") or ""),
    )
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/cards/{card_code}/refresh", response_model=ActionResult)
def refresh_card(card_code: str, payload: EntryPayload) -> ActionResult:
    """刷新指标卡：已被看板引用但尚未发布的指标会被明确阻止。"""
    card, message = service.refresh_card(card_code, str(payload.values.get("操作人") or ""))
    if card is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=card)


@router.get("/cards", response_model=dict)
def list_cards() -> dict[str, Any]:
    """指标卡清单：每张卡的引用版本、状态、最近处理结果与来源提交号。"""
    return {"items": service.cards()}


@router.get("/releases", response_model=dict)
def list_releases() -> dict[str, Any]:
    """看板发布记录：发布进度、卡片来源与影响清单都反映同一次提交。"""
    return {"items": service.releases()}


@router.get("/audits", response_model=dict)
def list_audits() -> dict[str, Any]:
    """审计记录：版本切换、引用切换、卡片重算与刷新阻止的留痕。"""
    return {"items": service.audits()}
