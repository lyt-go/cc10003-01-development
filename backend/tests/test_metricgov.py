"""口径影响面业务规则测试：预览分类、示例场景、并发发布、阻止与追溯。

直接跑服务层，不依赖 HTTP；每个用例前把内存仓库重置回种子数据。
运行：cd backend && .venv/bin/python -m unittest tests.test_metricgov -v
"""
from __future__ import annotations

import threading
import unittest

from app.services.metric import MetricService
from app.services.metricgov import (
    AUDIT_TABLE,
    CARD_TABLE,
    RELEASE_TABLE,
    VERSION_TABLE,
    MetricgovService,
)
from app.store import store


class MetricgovTestCase(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.service = MetricgovService()

    # ---------- 预览 ----------

    def test_preview_distinguishes_change_types(self) -> None:
        # 公式变化 → 数据影响，引用卡片预计待重算
        result, _ = self.service.preview("METR-0003", {"计算公式": "支付成功订单数 / 全部订单数"})
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["变更类型"], ["公式变化"])
        self.assertEqual(result["影响级别"], "数据影响")
        self.assertTrue(result["可发布"])
        self.assertEqual(result["引用看板"][0]["看板编号"], "DASH-0002")
        self.assertEqual(result["引用看板"][0]["预计处理"], "待重算")

        # 筛选变化 → 数据影响
        result, _ = self.service.preview("METR-0003", {"筛选条件": "支付渠道=线上"})
        assert result is not None
        self.assertEqual(result["变更类型"], ["筛选变化"])
        self.assertEqual(result["影响级别"], "数据影响")

        # 仅名称变化 → 展示影响，卡片复用原结果
        result, _ = self.service.preview("METR-0003", {"指标名称": "支付成功率（新）"})
        assert result is not None
        self.assertEqual(result["变更类型"], ["仅名称变化"])
        self.assertEqual(result["影响级别"], "展示影响")
        self.assertEqual(result["引用看板"][0]["预计处理"], "复用原结果")

        # 无变化 → 不可发布
        result, _ = self.service.preview("METR-0003", {})
        assert result is not None
        self.assertEqual(result["影响级别"], "无变化")
        self.assertFalse(result["可发布"])

    def test_preview_blocks_unpublished_metric(self) -> None:
        # METR-0001 还是草稿：已被 DASH-0001 引用，预览要明确提示阻止
        result, _ = self.service.preview("METR-0001", {"精度位数": "1"})
        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result["可发布"])
        self.assertEqual(result["引用看板"][0]["预计处理"], "已阻止")
        self.assertIn("尚未发布", result["提示"])

    # ---------- 示例场景：METR-0003 精度 2 位 → 1 位 ----------

    def test_precision_change_only_recalcs_referencing_card(self) -> None:
        result, message = self.service.publish(
            "METR-0003",
            {"精度位数": "1"},
            base_version="v1.0",
            dashboard_code="DASH-0002",
            operator="测试员",
        )
        self.assertIsNotNone(result, message)
        assert result is not None
        self.assertEqual(result["新版本"], "v1.1")
        self.assertEqual(result["变更类型"], ["精度变化"])
        self.assertEqual(result["发布进度"], "1/1")

        cards = {row["卡片编号"]: row for row in store.rows(CARD_TABLE)}
        # 只有 DASH-0002 这张卡进入待重算，引用切到 v1.1，来源提交号指向本次发布
        self.assertEqual(cards["CARD-0002"]["卡片状态"], "待重算")
        self.assertEqual(cards["CARD-0002"]["引用口径版本"], "v1.1")
        self.assertEqual(cards["CARD-0002"]["来源提交号"], result["提交号"])
        # DASH-0001 / DASH-0003 的卡片保持原结果，不被这次发布触碰
        self.assertEqual(cards["CARD-0001"]["卡片状态"], "已阻止")
        self.assertEqual(cards["CARD-0001"]["引用口径版本"], "—")
        self.assertEqual(cards["CARD-0003"]["卡片状态"], "已阻止")

        # 指标定义同步到新口径；历史版本仍可追溯
        metric = next(row for row in store.rows("metric") if row["指标编号"] == "METR-0003")
        self.assertEqual(metric["精度位数"], "1")
        self.assertEqual(metric["口径版本"], "v1.1")
        versions = self.service.versions("METR-0003")
        self.assertEqual([row["版本状态"] for row in versions], ["当前", "历史"])
        self.assertEqual(versions[1]["口径版本"], "v1.0")
        self.assertEqual(versions[1]["精度位数"], "2")

        # 发布记录、卡片来源、审计都挂在同一个提交号下
        release = next(row for row in store.rows(RELEASE_TABLE) if row["提交号"] == result["提交号"])
        self.assertEqual(release["发起看板"], "DASH-0002")
        self.assertEqual(release["影响卡片数"], 1)
        self.assertEqual(release["待重算数"], 1)
        audits = [row for row in store.rows(AUDIT_TABLE) if row["提交号"] == result["提交号"]]
        self.assertTrue(any(row["操作类型"] == "版本发布" for row in audits))
        self.assertTrue(any(row["操作类型"] == "引用切换" for row in audits))

    def test_display_only_change_reuses_results(self) -> None:
        result, _ = self.service.publish(
            "METR-0003", {"指标名称": "支付成功率（含退款）"},
            base_version="v1.0", dashboard_code="DASH-0002", operator="测试员",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["影响级别"], "展示影响")
        card = next(row for row in store.rows(CARD_TABLE) if row["卡片编号"] == "CARD-0002")
        # 引用切换到新版本，但卡片不进待重算，继续复用原结果
        self.assertEqual(card["引用口径版本"], "v1.1")
        self.assertEqual(card["卡片状态"], "正常")
        self.assertIn("复用原结果", card["最近处理结果"])

    # ---------- 并发发布 ----------

    def test_concurrent_publish_keeps_single_current_reference(self) -> None:
        before_releases = len(store.rows(RELEASE_TABLE))
        before_versions = len(store.rows(VERSION_TABLE))
        results: list[tuple[dict | None, str]] = []

        def attempt(dashboard: str) -> None:
            results.append(self.service.publish(
                "METR-0003", {"精度位数": "1"},
                base_version="v1.0", dashboard_code=dashboard, operator="并发测试",
            ))

        threads = [threading.Thread(target=attempt, args=(dash,)) for dash in ("DASH-0002", "DASH-0003")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        ok_results = [entry for entry, _ in results if entry]
        self.assertEqual(len(ok_results), 1, "并发发布只能成功一侧")
        # 失败一侧不留半套引用：版本表、发布记录只各多一条
        self.assertEqual(len(store.rows(RELEASE_TABLE)), before_releases + 1)
        self.assertEqual(len(store.rows(VERSION_TABLE)), before_versions + 1)
        current = [row for row in store.rows(VERSION_TABLE)
                   if row["指标编号"] == "METR-0003" and row["版本状态"] == "当前"]
        self.assertEqual(len(current), 1, "同一条指标最终只保留一份当前引用")
        # 指标卡引用一致指向唯一的当前版本
        for card in store.rows(CARD_TABLE):
            if card["指标编号"] == "METR-0003":
                self.assertEqual(card["引用口径版本"], current[0]["口径版本"])
        # 冲突一侧留下了审计留痕，但没有产生提交号
        conflicts = [row for row in store.rows(AUDIT_TABLE) if row["操作类型"] == "发布冲突"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["提交号"], "—")

    def test_stale_base_version_is_rejected(self) -> None:
        result, message = self.service.publish(
            "METR-0003", {"精度位数": "1"},
            base_version="v9.9", dashboard_code="DASH-0002", operator="测试员",
        )
        self.assertIsNone(result)
        self.assertIn("并发发布冲突", message)

    # ---------- 阻止与刷新 ----------

    def test_refresh_blocked_for_unpublished_metric(self) -> None:
        card, message = self.service.refresh_card("CARD-0001", "测试员")
        self.assertIsNone(card)
        self.assertIn("阻止", message)
        row = next(r for r in store.rows(CARD_TABLE) if r["卡片编号"] == "CARD-0001")
        self.assertEqual(row["卡片状态"], "已阻止")
        audits = [r for r in store.rows(AUDIT_TABLE) if r["操作类型"] == "刷新阻止"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["指标编号"], "METR-0001")

    def test_publish_rejected_for_unpublished_metric(self) -> None:
        result, message = self.service.publish(
            "METR-0001", {"精度位数": "1"},
            base_version="无", dashboard_code="DASH-0001", operator="测试员",
        )
        self.assertIsNone(result)
        self.assertIn("尚未发布", message)
        audits = [r for r in store.rows(AUDIT_TABLE) if r["操作类型"] == "发布阻止"]
        self.assertEqual(len(audits), 1)

    def test_first_release_then_refresh_unblocks_card(self) -> None:
        # 老流程把 METR-0001 推到已发布
        MetricService().run_action(1, "发布指标")
        result, message = self.service.publish(
            "METR-0001", {}, base_version="无", dashboard_code="DASH-0001", operator="测试员",
        )
        self.assertIsNotNone(result, message)
        assert result is not None
        self.assertEqual(result["新版本"], "v1.0")
        card = next(r for r in store.rows(CARD_TABLE) if r["卡片编号"] == "CARD-0001")
        self.assertEqual(card["卡片状态"], "待重算")
        # 重算后卡片恢复正常，来源提交号指向这次发布
        refreshed, message = self.service.refresh_card("CARD-0001", "测试员")
        self.assertIsNotNone(refreshed, message)
        assert refreshed is not None
        self.assertEqual(refreshed["卡片状态"], "正常")
        self.assertEqual(refreshed["引用口径版本"], "v1.0")
        self.assertEqual(refreshed["来源提交号"], result["提交号"])

    def test_refresh_recalculates_pending_card(self) -> None:
        result, _ = self.service.publish(
            "METR-0003", {"精度位数": "1"},
            base_version="v1.0", dashboard_code="DASH-0002", operator="测试员",
        )
        assert result is not None
        refreshed, message = self.service.refresh_card("CARD-0002", "测试员")
        self.assertIsNotNone(refreshed, message)
        assert refreshed is not None
        self.assertEqual(refreshed["卡片状态"], "正常")
        self.assertEqual(refreshed["引用口径版本"], "v1.1")
        self.assertEqual(refreshed["来源提交号"], result["提交号"])


if __name__ == "__main__":
    unittest.main()
