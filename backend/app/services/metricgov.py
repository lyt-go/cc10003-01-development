"""指标口径治理：口径版本、看板引用、指标卡重算与审计的业务规则。

数据流顺着「指标定义(metric) → 口径版本(metric_version) → 看板指标卡(metric_card)」走：
- 预览：对比当前口径版本，区分公式变化、筛选变化、仅名称变化等不同影响；
- 发布：一次提交（提交号）内原子完成版本切换 + 引用切换 + 影响清单 + 审计，
  只有受影响的指标卡进入待重算，未受影响的继续复用原结果；
- 并发：同一条指标被多个看板并发发布时，用锁 + 基准版本校验保证最终只保留
  一份当前引用，失败的一侧不留半套引用；
- 阻止：已被看板引用但尚未发布的指标，卡片刷新被明确阻止并留痕。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any

from app.store import store

METRIC_MODULE = "metric"
DASHBOARD_MODULE = "dashboard"
VERSION_TABLE = "metric_version"
CARD_TABLE = "metric_card"
RELEASE_TABLE = "metric_release"
AUDIT_TABLE = "metric_audit"

# 参与口径版本对比的字段；指标名称只影响展示，其余字段变化都会改变取数结果
CALIBER_FIELDS = ["指标名称", "计算公式", "统计粒度", "时间窗口", "筛选条件", "精度位数"]
CHANGE_TYPE_MAP = {
    "计算公式": "公式变化",
    "筛选条件": "筛选变化",
    "时间窗口": "时间窗口变化",
    "统计粒度": "统计粒度变化",
    "精度位数": "精度变化",
    "指标名称": "仅名称变化",
}
DATA_CHANGE_TYPES = {"公式变化", "筛选变化", "时间窗口变化", "统计粒度变化", "精度变化", "首次发布"}
DISPLAY_CHANGE_TYPES = {"仅名称变化"}

CARD_NORMAL = "正常"
CARD_PENDING = "待重算"
CARD_BLOCKED = "已阻止"

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_code(rows: list[dict[str, Any]], field: str, prefix: str) -> str:
    """按已有编号生成下一个顺序号，如 REL-0002。"""
    seq = 0
    for row in rows:
        match = re.fullmatch(rf"{prefix}-(\d+)", str(row.get(field, "")))
        if match:
            seq = max(seq, int(match.group(1)))
    return f"{prefix}-{seq + 1:04d}"


def _bump_version(current: str) -> str:
    match = re.fullmatch(r"v(\d+)\.(\d+)", current.strip())
    if match:
        return f"v{match.group(1)}.{int(match.group(2)) + 1}"
    return "v1.1"


class MetricgovService:
    # ---------- 基础查询 ----------

    def _metric_by_code(self, metric_code: str) -> dict[str, Any] | None:
        for row in store.rows(METRIC_MODULE):
            if row.get("指标编号") == metric_code:
                return row
        return None

    def _dashboard_by_code(self, dashboard_code: str) -> dict[str, Any] | None:
        for row in store.rows(DASHBOARD_MODULE):
            if row.get("看板编号") == dashboard_code:
                return row
        return None

    def _current_version(self, metric_code: str) -> dict[str, Any] | None:
        for row in store.rows(VERSION_TABLE):
            if row.get("指标编号") == metric_code and row.get("版本状态") == "当前":
                return row
        return None

    def _cards_of_metric(self, metric_code: str) -> list[dict[str, Any]]:
        return [row for row in store.rows(CARD_TABLE) if row.get("指标编号") == metric_code]

    def _card_by_code(self, card_code: str) -> dict[str, Any] | None:
        for row in store.rows(CARD_TABLE):
            if row.get("卡片编号") == card_code:
                return row
        return None

    @staticmethod
    def _caliber_of(source: dict[str, Any]) -> dict[str, str]:
        return {field: str(source.get(field) or "") for field in CALIBER_FIELDS}

    def _current_caliber(self, metric: dict[str, Any]) -> dict[str, str]:
        """当前生效口径：有已发布版本以版本表为准，否则用指标定义上的草稿口径。"""
        version = self._current_version(str(metric.get("指标编号")))
        return self._caliber_of(version) if version else self._caliber_of(metric)

    @staticmethod
    def _classify(current: dict[str, str], incoming: dict[str, str]) -> list[dict[str, str]]:
        """逐字段对比，产出变更明细：字段、旧值、新值、变更类型、影响级别。"""
        changes: list[dict[str, str]] = []
        for field in CALIBER_FIELDS:
            new_value = str(incoming.get(field) or "").strip()
            old_value = str(current.get(field) or "").strip()
            if new_value == "" or new_value == old_value:
                continue
            change_type = CHANGE_TYPE_MAP[field]
            changes.append({
                "字段": field,
                "旧值": old_value or "—",
                "新值": new_value,
                "变更类型": change_type,
                "影响级别": "数据影响" if change_type in DATA_CHANGE_TYPES else "展示影响",
            })
        return changes

    def _append_audit(
        self,
        *,
        release_no: str,
        action: str,
        metric_code: str,
        dashboard_code: str,
        old_version: str,
        new_version: str,
        affected: int,
        result: str,
        operator: str,
    ) -> dict[str, Any]:
        rows = store.rows(AUDIT_TABLE)
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "审计编号": _next_code(rows, "审计编号", "AUD"),
            "提交号": release_no,
            "操作类型": action,
            "指标编号": metric_code,
            "看板编号": dashboard_code,
            "旧版本": old_version,
            "新版本": new_version,
            "影响卡片数": affected,
            "操作结果": result,
            "操作时间": _now(),
            "操作人": operator,
        }
        rows.append(entry)
        return entry

    # ---------- 面板与档案 ----------

    def panel(self) -> dict[str, Any]:
        metrics = []
        cards = store.rows(CARD_TABLE)
        for metric in store.rows(METRIC_MODULE):
            code = str(metric.get("指标编号"))
            current = self._current_version(code)
            metric_cards = [card for card in cards if card.get("指标编号") == code]
            metrics.append({
                "指标编号": code,
                "指标名称": metric.get("指标名称"),
                "指标状态": metric.get("status"),
                "当前口径版本": current.get("口径版本") if current else "未发布",
                "统计粒度": metric.get("统计粒度"),
                "时间窗口": metric.get("时间窗口"),
                "引用看板数": len({card.get("看板编号") for card in metric_cards}),
                "待重算卡片": sum(1 for card in metric_cards if card.get("卡片状态") == CARD_PENDING),
                "已阻止卡片": sum(1 for card in metric_cards if card.get("卡片状态") == CARD_BLOCKED),
            })
        stats = [
            {"label": "指标定义", "value": len(metrics)},
            {"label": "指标卡", "value": len(cards)},
            {"label": "待重算", "value": sum(1 for card in cards if card.get("卡片状态") == CARD_PENDING)},
            {"label": "已阻止", "value": sum(1 for card in cards if card.get("卡片状态") == CARD_BLOCKED)},
        ]
        return {"stats": stats, "metrics": metrics}

    def metric_profile(self, metric_code: str) -> dict[str, Any] | None:
        metric = self._metric_by_code(metric_code)
        if metric is None:
            return None
        current = self._current_version(metric_code)
        caliber = self._current_caliber(metric)
        dashboards = []
        for card in self._cards_of_metric(metric_code):
            dashboard = self._dashboard_by_code(str(card.get("看板编号"))) or {}
            dashboards.append({
                "看板编号": card.get("看板编号"),
                "看板名称": card.get("看板名称"),
                "看板状态": dashboard.get("status", "未知"),
                "卡片编号": card.get("卡片编号"),
                "卡片状态": card.get("卡片状态"),
                "引用口径版本": card.get("引用口径版本"),
                "最近处理结果": card.get("最近处理结果"),
            })
        return {
            "指标编号": metric_code,
            "指标名称": metric.get("指标名称"),
            "指标状态": metric.get("status"),
            "当前口径版本": current.get("口径版本") if current else "未发布",
            **caliber,
            "引用看板": dashboards,
            "历史版本数": sum(
                1 for row in store.rows(VERSION_TABLE)
                if row.get("指标编号") == metric_code and row.get("版本状态") == "历史"
            ),
        }

    def versions(self, metric_code: str) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(VERSION_TABLE) if row.get("指标编号") == metric_code]
        return sorted(rows, key=lambda row: (row.get("版本状态") != "当前", -int(row.get("id", 0))))

    def cards(self) -> list[dict[str, Any]]:
        return sorted(store.rows(CARD_TABLE), key=lambda row: int(row.get("id", 0)))

    def releases(self) -> list[dict[str, Any]]:
        return sorted(store.rows(RELEASE_TABLE), key=lambda row: -int(row.get("id", 0)))

    def audits(self) -> list[dict[str, Any]]:
        return sorted(store.rows(AUDIT_TABLE), key=lambda row: -int(row.get("id", 0)))

    # ---------- 预览 ----------

    def preview(self, metric_code: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """发布前预览：告诉业务人员这次改动会影响哪些指标卡、影响级别是什么。"""
        metric = self._metric_by_code(metric_code)
        if metric is None:
            return None, f"指标定义 {metric_code} 不存在或已归档"
        current_version = self._current_version(metric_code)
        current_caliber = self._current_caliber(metric)
        incoming = {field: str(values.get(field) or "").strip() for field in CALIBER_FIELDS}
        changes = self._classify(current_caliber, incoming)
        change_types = [change["变更类型"] for change in changes]
        if current_version is None:
            change_types = ["首次发布"]
            changes = [{
                "字段": field,
                "旧值": "—",
                "新值": current_caliber[field] or "—",
                "变更类型": "首次发布",
                "影响级别": "数据影响",
            } for field in CALIBER_FIELDS]
        data_impact = any(change["变更类型"] in DATA_CHANGE_TYPES for change in changes)
        impact_level = "数据影响" if data_impact else ("展示影响" if changes else "无变化")
        published = metric.get("status") == "已发布"
        cards = []
        for card in self._cards_of_metric(metric_code):
            if not published:
                plan, reason = CARD_BLOCKED, "指标未发布，卡片刷新被阻止"
            elif data_impact:
                plan, reason = CARD_PENDING, "口径数据影响变化，需按新版本重算"
            elif changes:
                plan, reason = "复用原结果", "仅展示名称变化，不重算"
            else:
                plan, reason = "复用原结果", "口径无变化"
            cards.append({
                "卡片编号": card.get("卡片编号"),
                "看板编号": card.get("看板编号"),
                "看板名称": card.get("看板名称"),
                "当前引用版本": card.get("引用口径版本"),
                "卡片状态": card.get("卡片状态"),
                "预计处理": plan,
                "原因": reason,
            })
        if not published:
            notice = "指标已被看板引用但尚未发布：卡片刷新被阻止，也不能发布新口径版本"
        elif not changes:
            notice = "与当前口径完全一致，无需发布新版本"
        else:
            notice = "预览通过，可按基准版本发起发布"
        return {
            "指标编号": metric_code,
            "指标名称": metric.get("指标名称"),
            "指标状态": metric.get("status"),
            "当前口径版本": current_version.get("口径版本") if current_version else "未发布",
            "统计粒度": current_caliber["统计粒度"],
            "时间窗口": current_caliber["时间窗口"],
            "变更类型": change_types,
            "变更明细": changes,
            "影响级别": impact_level,
            "引用看板": cards,
            "可发布": bool(published and changes),
            "提示": notice,
        }, ""

    # ---------- 发布 ----------

    def publish(
        self,
        metric_code: str,
        values: dict[str, Any],
        *,
        base_version: str,
        dashboard_code: str,
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """发布新口径版本：一次提交原子完成，失败一侧不留半套引用。

        并发安全：整段校验 + 写入都在同一把锁里；基准版本不一致直接判冲突，
        不做任何写入，保证同一条指标最终只保留一份当前引用。
        """
        with _LOCK:
            metric = self._metric_by_code(metric_code)
            if metric is None:
                return None, f"指标定义 {metric_code} 不存在或已归档"
            if metric.get("status") != "已发布":
                self._append_audit(
                    release_no="—", action="发布阻止", metric_code=metric_code,
                    dashboard_code=dashboard_code or "—", old_version="—", new_version="—",
                    affected=len(self._cards_of_metric(metric_code)), result="已阻止",
                    operator=operator or "未知",
                )
                return None, f"指标 {metric_code} 尚未发布，不能发布新口径版本；引用它的指标卡保持阻止状态"

            current_version = self._current_version(metric_code)
            current_version_no = current_version.get("口径版本") if current_version else "无"
            expected = (base_version or "无").strip() or "无"
            if expected != str(current_version_no):
                self._append_audit(
                    release_no="—", action="发布冲突", metric_code=metric_code,
                    dashboard_code=dashboard_code or "—",
                    old_version=str(current_version_no), new_version="—",
                    affected=0, result="失败", operator=operator or "未知",
                )
                return None, (
                    f"并发发布冲突：当前口径版本已是 {current_version_no}，"
                    f"本次基于 {expected} 的发布未生效，未留下任何引用变更"
                )

            current_caliber = self._current_caliber(metric)
            incoming = {field: str(values.get(field) or "").strip() for field in CALIBER_FIELDS}
            changes = self._classify(current_caliber, incoming)
            first_release = current_version is None
            if not first_release and not changes:
                return None, "与当前口径完全一致，无需发布新版本"

            release_no = _next_code(store.rows(RELEASE_TABLE), "提交号", "REL")
            new_version_no = "v1.0" if first_release else _bump_version(str(current_version_no))
            change_types = [change["变更类型"] for change in changes] or ["首次发布"]
            data_impact = first_release or any(t in DATA_CHANGE_TYPES for t in change_types)
            merged = {**current_caliber, **{k: v for k, v in incoming.items() if v}}
            now = _now()
            operator_name = operator or "值班管理员"

            # 1) 版本切换：旧当前版本转历史，写入唯一的新当前版本
            if current_version is not None:
                current_version["版本状态"] = "历史"
            version_rows = store.rows(VERSION_TABLE)
            version_rows.append({
                "id": max((int(row.get("id", 0)) for row in version_rows), default=0) + 1,
                "版本编号": _next_code(version_rows, "版本编号", "MV"),
                "指标编号": metric_code,
                "指标名称": merged["指标名称"] or metric.get("指标名称"),
                "口径版本": new_version_no,
                "计算公式": merged["计算公式"],
                "统计粒度": merged["统计粒度"],
                "时间窗口": merged["时间窗口"],
                "筛选条件": merged["筛选条件"],
                "精度位数": merged["精度位数"],
                "变更类型": "、".join(change_types),
                "版本状态": "当前",
                "提交号": release_no,
                "发布时间": now,
                "发布人": operator_name,
            })

            # 2) 指标定义同步到最新口径
            for field in CALIBER_FIELDS:
                if incoming.get(field):
                    metric[field] = incoming[field]
            metric["口径版本"] = new_version_no

            # 3) 引用切换：同一提交号下逐卡处理，受影响待重算，未受影响复用原结果
            card_results = []
            pending_count = reuse_count = 0
            for card in self._cards_of_metric(metric_code):
                old_ref = str(card.get("引用口径版本") or "—")
                card["引用口径版本"] = new_version_no
                card["来源提交号"] = release_no
                card["更新时间"] = now
                if data_impact:
                    card["卡片状态"] = CARD_PENDING
                    card["最近处理结果"] = f"口径 {new_version_no} 已发布，等待重算"
                    pending_count += 1
                else:
                    card["最近处理结果"] = f"复用原结果（{'、'.join(change_types)}）"
                    reuse_count += 1
                card_results.append({
                    "卡片编号": card.get("卡片编号"),
                    "看板编号": card.get("看板编号"),
                    "看板名称": card.get("看板名称"),
                    "旧引用版本": old_ref,
                    "新引用版本": new_version_no,
                    "处理结果": card.get("卡片状态") if data_impact else "复用原结果",
                })
                self._append_audit(
                    release_no=release_no, action="引用切换", metric_code=metric_code,
                    dashboard_code=str(card.get("看板编号")), old_version=old_ref,
                    new_version=new_version_no, affected=1,
                    result="待重算" if data_impact else "复用原结果", operator=operator_name,
                )

            # 4) 看板发布记录：进度、卡片来源、影响清单都挂在同一个提交号下
            release_rows = store.rows(RELEASE_TABLE)
            release = {
                "id": max((int(row.get("id", 0)) for row in release_rows), default=0) + 1,
                "提交号": release_no,
                "指标编号": metric_code,
                "指标名称": merged["指标名称"] or metric.get("指标名称"),
                "口径版本": new_version_no,
                "变更类型": "、".join(change_types),
                "发起看板": dashboard_code or "—",
                "影响卡片数": len(card_results),
                "待重算数": pending_count,
                "复用结果数": reuse_count,
                "阻止数": 0,
                "发布状态": "已完成",
                "发布时间": now,
                "操作人": operator_name,
            }
            release_rows.append(release)

            # 5) 审计：版本切换与发布同步留痕
            self._append_audit(
                release_no=release_no, action="版本发布", metric_code=metric_code,
                dashboard_code=dashboard_code or "—", old_version=str(current_version_no),
                new_version=new_version_no, affected=len(card_results),
                result="已完成", operator=operator_name,
            )

            total = len(card_results)
            return {
                "提交号": release_no,
                "指标编号": metric_code,
                "新版本": new_version_no,
                "变更类型": change_types,
                "影响级别": "数据影响" if data_impact else "展示影响",
                "影响卡片": card_results,
                "发布进度": f"{total}/{total}",
                "发布状态": "已完成",
                "提示": (
                    f"发布完成：{total} 张指标卡中 {pending_count} 张进入待重算，"
                    f"{reuse_count} 张复用原结果"
                ),
            }, f"指标 {metric_code} 已发布口径版本 {new_version_no}（提交号 {release_no}）"

    # ---------- 卡片刷新 ----------

    def refresh_card(self, card_code: str, operator: str) -> tuple[dict[str, Any] | None, str]:
        """刷新单张指标卡；指标未发布时明确阻止并留痕。"""
        with _LOCK:
            card = self._card_by_code(card_code)
            if card is None:
                return None, f"指标卡 {card_code} 不存在或已归档"
            metric_code = str(card.get("指标编号"))
            metric = self._metric_by_code(metric_code)
            operator_name = operator or "值班管理员"
            if metric is None:
                return None, f"指标卡 {card_code} 引用的指标 {metric_code} 不存在"
            if metric.get("status") != "已发布":
                card["卡片状态"] = CARD_BLOCKED
                card["最近处理结果"] = "指标未发布，卡片刷新被阻止"
                card["更新时间"] = _now()
                self._append_audit(
                    release_no=str(card.get("来源提交号") or "—"), action="刷新阻止",
                    metric_code=metric_code, dashboard_code=str(card.get("看板编号")),
                    old_version=str(card.get("引用口径版本") or "—"),
                    new_version=str(card.get("引用口径版本") or "—"),
                    affected=1, result="已阻止", operator=operator_name,
                )
                return None, f"指标 {metric_code} 尚未发布，指标卡 {card_code} 刷新被明确阻止"
            current_version = self._current_version(metric_code)
            if current_version is None:
                return None, f"指标 {metric_code} 已发布但还没有口径版本，请先在口径影响面发布首个版本"
            version_no = str(current_version.get("口径版本"))
            old_ref = str(card.get("引用口径版本") or "—")
            card["引用口径版本"] = version_no
            card["卡片状态"] = CARD_NORMAL
            card["最近处理结果"] = f"已按 {version_no} 重算"
            card["来源提交号"] = str(current_version.get("提交号"))
            card["更新时间"] = _now()
            self._append_audit(
                release_no=str(current_version.get("提交号")), action="卡片重算",
                metric_code=metric_code, dashboard_code=str(card.get("看板编号")),
                old_version=old_ref, new_version=version_no,
                affected=1, result="已完成", operator=operator_name,
            )
            return card, f"指标卡 {card_code} 已按口径 {version_no} 重算完成"
