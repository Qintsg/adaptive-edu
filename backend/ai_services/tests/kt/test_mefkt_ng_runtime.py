#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
验证 MEFKT-NG 模型包、课程目录和现有 KT 接口的在线适配。
@Project : adaptive-edu
@File : test_mefkt_ng_runtime.py
@Author : Qintsg
@Date : 2026-09-25
'''

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase

from ai_services.services.kt.prediction_support import is_mefkt_prediction
from ai_services.services.mefkt.ng_course_data import (
    NGCourseSpec, NGPointSpec, NGQuestionSpec, course_revision, load_course_spec,
)
from ai_services.services.mefkt.ng_runtime import NGPredictor
from ai_services.services.mefkt.ng_sequence import predict_candidates, prepare_history


BUNDLE = Path(__file__).resolve().parents[3] / "models" / "MEFKT_NG"


def fake_encode(texts: list[str]) -> np.ndarray:
    """构造确定性 384 维非零文本向量，避免测试下载外部编码器。

    :param texts: 静态题目文本。
    :returns: `[N,384]` float32 矩阵。
    """
    rows = []
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).digest() * 12
        rows.append(np.frombuffer(digest, dtype=np.uint8).astype(np.float32) - 127.5)
    return np.stack(rows)


def fake_course(revision: str = "initial") -> NGCourseSpec:
    """生成两个题目、两个知识点的纯内存课程。

    :param revision: 缓存修订标识。
    :returns: 测试课程静态快照。
    """
    points = (NGPointSpec(101, "比例", "比例计算"), NGPointSpec(102, "函数", "函数求值"))
    questions = (
        NGQuestionSpec(201, "2:3 = 4:?", ("5", "6"), "single_choice", "easy", (101,)),
        NGQuestionSpec(202, "f(x)=x+1，f(2)=?", ("2", "3"), "single_choice", "medium", (102,)),
    )
    return NGCourseSpec(7, "数学", points, questions,
                        revision if revision != "initial" else course_revision("数学", points, questions))


class MEFKTNGOnlineTests(SimpleTestCase):
    """不访问数据库，检查实际导出的模型权重和因果事件映射。"""

    def test_default_auto_loader_activates_ng_bundle(self) -> None:
        """无显式配置时后端应加载新权重而非旧 `.pt`。

        :returns: None。
        """
        from ai_services.services.mefkt.inference import MEFKTPredictor
        from ai_services.services.mefkt.loader import auto_load_mefkt_model

        predictor = MEFKTPredictor()
        self.assertTrue(auto_load_mefkt_model(predictor, BUNDLE.parents[1], {}))
        self.assertEqual(predictor.get_info()["runtime_mode"], "ng")
        self.assertEqual(predictor.get_info()["selected_epoch"], 136)

    def test_explicit_legacy_mode_loads_old_checkpoint(self) -> None:
        """显式回滚开关保留旧权重的加载能力。

        :returns: None。
        """
        from ai_services.services.mefkt.inference import MEFKTPredictor
        from ai_services.services.mefkt.loader import auto_load_mefkt_model

        predictor = MEFKTPredictor()
        self.assertTrue(auto_load_mefkt_model(predictor, BUNDLE.parents[1],
                                               {"KT_MEFKT_RUNTIME": "legacy"}))
        self.assertNotEqual(predictor.get_info()["runtime_mode"], "ng")

    def test_real_bundle_returns_course_point_predictions(self) -> None:
        """真实权重包能为新课程返回旧 KT 接口所需的知识点概率。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        history: list[dict[str, Any]] = [
            {"question_id": 201, "knowledge_point_id": 101, "correct": 1,
             "timestamp": "2026-09-24T08:00:00Z"},
            {"question_id": 202, "knowledge_point_id": 102, "correct": 0,
             "timestamp": "2026-09-24T08:10:00Z"},
        ]
        result = runtime.predict(history, [101, 102], 7)
        self.assertEqual(result["model_type"], "mefkt_ng")
        self.assertTrue(is_mefkt_prediction(result))
        self.assertEqual(set(result["predictions"]), {101, 102})
        self.assertEqual(set(result["question_predictions"]), {201, 202})
        self.assertTrue(all(0.0 <= value <= 1.0 for value in result["predictions"].values()))
        self.assertIn("2/2", result["analysis"])

    def test_zero_is_a_valid_incorrect_answer_and_exam_is_one_episode(self) -> None:
        """0 标签不可当缺失；同一考试多题不得逐题泄漏。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        catalog = runtime._course_catalog(7)
        history = prepare_history([
            {"question_id": 201, "correct": 0, "exam_id": 42,
             "timestamp": "2026-09-24T08:00:00Z"},
            {"question_id": 202, "correct": 1, "exam_id": 42,
             "timestamp": "2026-09-24T08:02:00Z"},
        ], catalog, 168)
        self.assertEqual(history.correct, (0.0, 1.0))
        self.assertEqual(history.episodes, (0, 0))

    def test_foreign_question_does_not_fall_back_to_current_course_point(self) -> None:
        """显式外课题目不能借当前课知识点伪装成一次作答。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        catalog = runtime._course_catalog(7)
        history = prepare_history([
            {"question_id": 999, "knowledge_point_id": 101, "correct": 1},
            {"knowledge_point_id": 101, "correct": 0},
        ], catalog, 168)
        self.assertEqual(history.recognized_count, 1)
        self.assertEqual(history.items, (catalog.question_index[201],))
        self.assertEqual(history.correct, (0.0,))

    def test_only_foreign_history_does_not_claim_real_ng_mastery(self) -> None:
        """当前课程无可识别作答时应让上层回退，避免冷启动高分冒充证据。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        result = runtime.predict([
            {"question_id": 999, "knowledge_point_id": 101, "correct": 1},
        ], [101], 7)
        self.assertEqual(result["predictions"], {})
        self.assertFalse(is_mefkt_prediction(result))

    def test_float_binary_scores_are_preserved(self) -> None:
        """业务历史中的 0.0/1.0 应与整数评分等价。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        catalog = runtime._course_catalog(7)
        history = prepare_history([
            {"question_id": 201, "correct": 0.0},
            {"question_id": 202, "correct": 1.0},
        ], catalog, 168)
        self.assertEqual(history.correct, (0.0, 1.0))

    def test_correct_history_improves_same_question_probe(self) -> None:
        """模型消费真实结果后，答对同一知识点不应比答错更差。

        :returns: None。
        """
        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), fake_encode)
        catalog = runtime._course_catalog(7)
        at = datetime(2026, 9, 24, 9, 0, tzinfo=UTC)
        outcomes = []
        for correct in (0, 1):
            history = prepare_history([{"question_id": 201, "correct": correct,
                                        "timestamp": "2026-09-24T08:00:00Z"}], catalog, 168)
            outcomes.append(predict_candidates(catalog, history, [catalog.question_index[201]], at)[0])
        self.assertGreater(outcomes[1], outcomes[0])

    def test_course_catalog_rebuilds_only_after_revision_change(self) -> None:
        """课程内容不变时复用编码，修订后重新构建。

        :returns: None。
        """
        state = {"revision": "r1", "encodes": 0}

        def loader(_course_id: int) -> NGCourseSpec:
            """提供当前修订课程。

            :param _course_id: 课程 ID。
            :returns: 课程静态快照。
            """
            return fake_course(state["revision"])

        def encoder(texts: list[str]) -> np.ndarray:
            """累计真实编码次数。

            :param texts: 编码文本。
            :returns: 测试向量。
            """
            state["encodes"] += 1
            return fake_encode(texts)

        runtime = NGPredictor(BUNDLE, loader, encoder)
        runtime._course_catalog(7)
        runtime._course_catalog(7)
        self.assertEqual(state["encodes"], 1)
        state["revision"] = "r2"
        runtime._course_catalog(7)
        self.assertEqual(state["encodes"], 2)

    def test_parallel_requests_build_one_catalog_per_revision(self) -> None:
        """同一课程并发冷请求应只编码和构建一次。

        :returns: None。
        """
        state = {"encodes": 0}
        counter_lock = threading.Lock()
        start = threading.Barrier(3)

        def encoder(texts: list[str]) -> np.ndarray:
            """放慢编码以稳定复现并发缓存未命中。

            :param texts: 待编码课程文本。
            :returns: 确定性内容向量。
            """
            with counter_lock:
                state["encodes"] += 1
            time.sleep(0.1)
            return fake_encode(texts)

        def request_catalog(_index: int) -> object:
            """模拟同时到达的课程预测请求。

            :param _index: 并发请求序号。
            :returns: 已构造的课程目录。
            """
            start.wait()
            return runtime._course_catalog(7)

        runtime = NGPredictor(BUNDLE, lambda _course_id: fake_course(), encoder)
        with ThreadPoolExecutor(max_workers=3) as pool:
            catalogs = list(pool.map(request_catalog, range(3)))
        self.assertEqual(state["encodes"], 1)
        self.assertTrue(all(catalog is catalogs[0] for catalog in catalogs))


class MEFKTNGCourseDatabaseTests(TestCase):
    """在真实 Django 题库关系上验证课程适配边界。"""

    def test_database_course_uses_visible_question_without_answer_leakage(self) -> None:
        """隐藏题不入目录，标准答案和解析不进入编码文本。

        :returns: None。
        """
        from assessments.models import Question
        from courses.models import Course
        from knowledge.models import KnowledgePoint

        course = Course.objects.create(name="函数课")
        point = KnowledgePoint.objects.create(course=course, name="一次函数", description="线性关系")
        visible = Question.objects.create(
            course=course, content="<p>f(1) 等于几？</p>", question_type="single_choice",
            options=[{"label": "A", "content": "2"}, {"label": "B", "content": "3"}],
            answer={"answer": "A"}, analysis="私有标准答案解析", difficulty="easy",
        )
        visible.knowledge_points.add(point)
        hidden = Question.objects.create(
            course=course, content="隐藏题", question_type="single_choice",
            answer={"answer": "B"}, is_visible=False,
        )
        hidden.knowledge_points.add(point)
        spec = load_course_spec(int(course.id))
        self.assertEqual([question.id for question in spec.questions], [visible.id])
        captured: list[str] = []

        def encoder(texts: list[str]) -> np.ndarray:
            """检查内容编码器只接收学生可见信息。

            :param texts: 待编码静态文本。
            :returns: 测试向量。
            """
            captured.extend(texts)
            return fake_encode(texts)

        runtime = NGPredictor(BUNDLE, load_course_spec, encoder)
        result = runtime.predict([{"question_id": visible.id, "correct": 1,
                                   "timestamp": "2026-09-24T08:00:00Z"}], [point.id], int(course.id))
        self.assertIn(int(point.id), result["predictions"])
        self.assertNotIn(int(hidden.id), result["question_predictions"])
        self.assertFalse(any("私有标准答案解析" in text or "隐藏题" in text for text in captured))

    def test_kt_service_routes_real_course_through_ng_by_default(self) -> None:
        """旧 KT 公开入口以相同返回结构使用新模型。

        :returns: None。
        """
        from assessments.models import Question
        from courses.models import Course
        from knowledge.models import KnowledgePoint
        from ai_services.services.kt.service import KnowledgeTracingService
        from ai_services.services.mefkt.inference import MEFKTPredictor

        course = Course.objects.create(name="线性代数")
        point = KnowledgePoint.objects.create(course=course, name="矩阵加法")
        question = Question.objects.create(
            course=course, content="两个矩阵如何相加？", question_type="single_choice",
            options=[{"label": "A", "content": "逐项相加"}, {"label": "B", "content": "行列式相加"}],
            answer={"answer": "A"}, difficulty="medium",
        )
        question.knowledge_points.add(point)
        predictor = MEFKTPredictor()
        self.assertTrue(predictor.load_model(str(BUNDLE)))
        self.assertEqual(predictor.get_info()["runtime_mode"], "ng")
        assert predictor._ng_predictor is not None
        predictor._ng_predictor._injected_encoder = fake_encode
        service = KnowledgeTracingService(prediction_mode="single", enabled_models=["mefkt"])
        with patch("ai_services.services.mefkt.inference.mefkt_predictor", predictor):
            result = service.predict_mastery(
                user_id=1, course_id=int(course.id),
                answer_history=[{"question_id": int(question.id), "knowledge_point_id": int(point.id),
                                 "correct": 1, "timestamp": "2026-09-24T08:00:00Z"}],
                knowledge_points=[int(point.id)],
            )
        self.assertEqual(result["model_type"], "mefkt_ng")
        self.assertIn(int(point.id), result["predictions"])
        self.assertEqual(result["prediction_mode"], "single")
        self.assertTrue(is_mefkt_prediction(result))

    def test_unavailable_content_encoder_uses_statistical_fallback(self) -> None:
        """编码器缺失时保持业务接口可用，且不谎称为真实模型输出。

        :returns: None。
        """
        from assessments.models import Question
        from courses.models import Course
        from knowledge.models import KnowledgePoint
        from ai_services.services.kt.service import KnowledgeTracingService
        from ai_services.services.mefkt.inference import MEFKTPredictor

        course = Course.objects.create(name="统计学")
        point = KnowledgePoint.objects.create(course=course, name="均值")
        question = Question.objects.create(
            course=course, content="求均值", question_type="single_choice",
            answer={"answer": "A"}, difficulty="easy",
        )
        question.knowledge_points.add(point)
        predictor = MEFKTPredictor()
        self.assertTrue(predictor.load_model(str(BUNDLE)))
        assert predictor._ng_predictor is not None

        def fail_encoding(_texts: list[str]) -> np.ndarray:
            """模拟离线环境缺少内容编码器。

            :param _texts: 待编码文本。
            :raises OSError: 编码器不可用。
            """
            raise OSError("编码器不可用")

        predictor._ng_predictor._injected_encoder = fail_encoding
        service = KnowledgeTracingService(prediction_mode="single", enabled_models=["mefkt"])
        with patch("ai_services.services.mefkt.inference.mefkt_predictor", predictor):
            result = service.predict_mastery(
                user_id=1, course_id=int(course.id),
                answer_history=[{"question_id": int(question.id), "knowledge_point_id": int(point.id),
                                 "correct": 0, "timestamp": "2026-09-24T08:00:00Z"}],
                knowledge_points=[int(point.id)],
            )
        self.assertIn(int(point.id), result["predictions"])
        self.assertFalse(is_mefkt_prediction(result))
