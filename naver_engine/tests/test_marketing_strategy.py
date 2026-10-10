"""전략 초안은 저장판 근거만 쓰며 AI 호출·광고 실행을 자동으로 시작하지 않는다."""
from copy import deepcopy
from datetime import date
import json
import io
import unittest

from naver_engine.tests.test_report_enrichment import rows, snapshot
from naver_engine import reporting as R
from naver_runtime import claude_provider as C


class MarketingStrategyTests(unittest.TestCase):
    def test_context_contains_only_numeric_evidence_and_baseline_is_not_ai(self):
        from naver_engine import marketing_strategy as M
        report = snapshot()
        report.update(report_id=987654, possibility_id=876543, client_name="PRIVATE CLIENT")
        report["details"].update(internal_note="PRIVATE NOTE", notes_history=["PRIVATE HISTORY"])
        saved = deepcopy(report)
        context = M.build_context(report)
        wire = json.dumps(context, ensure_ascii=False, allow_nan=False)
        for private in ("987654", "876543", "PRIVATE", "customer_id", "account_key", "fingerprint", "period_key"):
            self.assertNotIn(private, wire)
        self.assertEqual(len(context["metrics"]), 17)
        result = M.rule_based(report)
        self.assertEqual(result["source"], "rule_based")
        self.assertEqual(set(result["document"]), M.DOCUMENT_FIELDS)
        self.assertIn("미연결", result["document"]["competitive_response"])
        self.assertEqual(result["document"]["appeal_points"], [])
        self.assertIn("7,000원", result["document"]["diagnosis"])
        self.assertTrue(result["references"])
        self.assertEqual(report, saved)

    def test_provider_numeric_citations_are_resolved_and_fabricated_numbers_refused(self):
        from naver_engine import marketing_strategy as M
        report = snapshot()
        context = M.build_context(report)
        seen = []
        def fake(clean):
            seen.append(clean)
            return {**M.document_template(), "diagnosis": "관측: {{metric:spend.current}}. 목표 확인이 필요합니다."}
        result = M.generate(report, provider=fake)
        self.assertEqual(result["source"], "claude")
        self.assertIn("7,000원", result["document"]["diagnosis"])
        self.assertEqual(result["references"], [{"metric_key": "spend", "field": "current"}])
        self.assertEqual(seen, [context])
        for bad in ("예상 매출 999만원", "효율 ５０% 개선", "비용 ②배", "원인 <script>alert()</script>", "제어\x00문자",
                    "{{metric:private.current}}", "{{metric:spend.secret}}"):
            with self.subTest(bad=bad), self.assertRaises(M.StrategyRefused):
                M.validate_document({**M.document_template(), "diagnosis": bad}, context)

    def test_missing_partial_and_changed_scope_do_not_become_comparable_or_purchase_experiments(self):
        from naver_engine import marketing_strategy as M
        current = rows()
        current[-1].update(conversion_complete=False, conversions=None, conversion_value=None)
        report = snapshot(current=current)
        result = M.rule_based(report)
        self.assertIn("미완결", result["document"]["diagnosis"])
        self.assertIn("일부 완결 자료", result["document"]["diagnosis"])
        self.assertIn("일반 광고 전환", result["document"]["funnel_comment"])
        self.assertIn("승자", result["document"]["ab_comment"])
        context = M.build_context(report)
        with self.assertRaises(M.StrategyRefused):
            M.validate_document({**M.document_template(), "diagnosis": "{{metric:conversions.percent}}"}, context)
        with self.assertRaises(M.StrategyRefused):
            M.validate_document({**M.document_template(), "appeal_points": [
                {"title": "우수 상품", "message": "최고 품질", "basis": "고객 선호"}]}, context)
        changed = M.build_context(snapshot(customers=(101, 202)))
        with self.assertRaises(M.StrategyRefused):
            M.validate_document({**M.document_template(), "diagnosis": "{{metric:spend.absolute}}"}, changed)
        empty = M.rule_based(snapshot(current=[]))
        self.assertIn("확인 가능한 성과 수치가 없습니다", empty["document"]["diagnosis"])

    def test_anthropic_adapter_uses_explicit_model_bounded_fake_transport_without_retries(self):
        from naver_engine import marketing_strategy as M
        class Response(io.BytesIO):
            status = 200
        calls = []
        responses = []
        document = M.document_template()
        document["diagnosis"] = "{{metric:clicks.current}}를 확인하고 유입 근거를 대조합니다."
        body = json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(document)}]}).encode()
        def transport(request, *, timeout):
            calls.append((request, timeout))
            response = Response(body)
            responses.append(response)
            return response
        provider = C.AnthropicProvider.from_environment(
            {"ANTHROPIC_API_KEY": "fake-test-key", "CLAUDE_MODEL": "explicit-test-model"}, transport=transport)
        result = M.generate(snapshot(), provider=provider)
        self.assertIn("70", result["document"]["diagnosis"])
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_method(), "POST")
        self.assertFalse(request.allow_redirects)
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], "explicit-test-model")
        self.assertLessEqual(timeout, 20)
        self.assertNotIn("_account_reports", request.data.decode())
        self.assertTrue(responses[0].closed)
        with self.assertRaises(M.StrategyRefused):
            C.AnthropicProvider.from_environment({"CLAUDE_API_KEY": "fake-test-key"}, transport=transport)
        for response_body in (b"x"*(C.MAX_RESPONSE_BYTES+1), b'{"content":[],"content":[]}', b"not JSON"):
            with self.subTest(body_size=len(response_body)), self.assertRaises(M.StrategyRefused) as caught:
                M.generate(snapshot(), provider=C.AnthropicProvider("fake-test-key", "explicit-test-model",
                    transport=lambda request, timeout: Response(response_body)))
            self.assertNotIn(response_body[:20].decode(errors="replace"), str(caught.exception))

    def test_staff_document_allows_numeric_text_but_keeps_shape_and_plain_text_limits(self):
        from naver_engine import marketing_strategy as M
        document = M.document_template()
        document["diagnosis"] = "담당자 확인: 광고비 7,000원, 전환 14건.\n추적 정의와 다음 계획을 확인합니다."
        document["appeal_points"] = [{"title": "확인한 구성", "message": "1인분 상품", "basis": "담당자가 확인한 상품 상세페이지"}]
        self.assertEqual(M.normalize_document(document), document)
        for bad in ({**document, "private_note": "비공개"}, {**document, "direction": "<b>HTML</b>"},
                    {**document, "direction": "숨김\u202e문자"}, {**document, "direction": "a"*1401},
                    {**document, "weekly_plan": [{"action": "실행", "reason": "확인", "criterion": "검수", "id": 1}]}):
            with self.subTest(bad_fields=list(bad)), self.assertRaises(M.StrategyRefused):
                M.normalize_document(bad)

    def test_provider_failure_is_single_attempt_and_never_exposes_raw_errors(self):
        from naver_engine import marketing_strategy as M
        calls = []
        def failing(request, *, timeout):
            calls.append(True)
            raise OSError("RAW_SECRET_OR_PROVIDER_BODY")
        provider = C.AnthropicProvider("fake-test-key", "explicit-test-model", transport=failing)
        with self.assertRaises(M.StrategyRefused) as caught:
            M.generate(snapshot(), provider=provider)
        self.assertEqual(calls, [True])
        self.assertEqual(str(caught.exception), "PROVIDER_UNAVAILABLE")
        self.assertIsNone(caught.exception.__cause__)

    def test_expanded_references_cannot_exceed_final_document_limit(self):
        from naver_engine import marketing_strategy as M
        current = rows(spend=1_000_000_000_000)
        current[-1].update(basic_complete=False, spend=None, clk=None, imp=None)
        context = M.build_context(snapshot(current=current))
        document = M.document_template()
        document["diagnosis"] = "{{metric:spend.current}}"*75
        with self.assertRaises(M.StrategyRefused):
            M.validate_document(document, context)

    def test_zero_missing_and_calendar_comparisons_remain_distinct(self):
        from naver_engine import marketing_strategy as M
        zero = snapshot(current=rows(conversions=0, conversion_value=0))
        context = M.build_context(zero)
        valid = {**M.document_template(), "diagnosis": "{{metric:conversions.current}}를 확인합니다."}
        self.assertIn("현재 0", M.validate_document(valid, context)["diagnosis"])
        with self.assertRaises(M.StrategyRefused):
            M.validate_document({**valid, "diagnosis": "{{metric:cpa.current}}"}, context)
        with self.assertRaises(M.StrategyRefused):
            M.validate_document(valid, M.build_context(snapshot(current=[])))
        monthly = snapshot(target=R.period("monthly", date(2026, 3, 15)))
        self.assertIn("기간 길이가 달라", M.rule_based(monthly)["document"]["diagnosis"])
        self.assertIn("범위가 바뀌어", M.rule_based(snapshot(customers=(101, 202)))["document"]["diagnosis"])

    def test_malformed_context_and_truncated_provider_response_fail_closed(self):
        from naver_engine import marketing_strategy as M
        for report in ({}, {"period": {"kind": "weekly", "days": True}},
                       {"period": {"kind": "daily", "days": 1}}):
            with self.subTest(report=report), self.assertRaises(M.StrategyRefused) as caught:
                M.build_context(report)
            self.assertEqual(str(caught.exception), "CONTEXT_INVALID")
        class Response(io.BytesIO):
            status = 200
        body = json.dumps({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "PRIVATE RAW"}]}).encode()
        with self.assertRaises(M.StrategyRefused) as caught:
            M.generate(snapshot(), provider=C.AnthropicProvider("fake-test-key", "explicit-test-model",
                transport=lambda request, timeout: Response(body)))
        self.assertEqual(str(caught.exception), "PROVIDER_RESPONSE_INVALID")

    def test_environment_keys_cannot_enable_default_transport_and_redirects_are_refused(self):
        from naver_engine import marketing_strategy as M
        provider = C.AnthropicProvider.from_environment(
            {"ANTHROPIC_API_KEY": "fake-test-key", "CLAUDE_MODEL": "explicit-test-model"})
        with self.assertRaises(M.StrategyRefused) as caught:
            M.generate(snapshot(), provider=provider)
        self.assertEqual(str(caught.exception), "PROVIDER_TRANSPORT_DISABLED")
        class Response(io.BytesIO):
            status = 302
            read_calls = 0
            def read(self, *args):
                self.read_calls += 1
                return super().read(*args)
        calls = []
        response = Response(b"PRIVATE REDIRECT BODY")
        def transport(request, *, timeout):
            calls.append(request)
            self.assertFalse(request.allow_redirects)
            return response
        with self.assertRaises(M.StrategyRefused) as caught:
            M.generate(snapshot(), provider=C.AnthropicProvider("fake-test-key", "explicit-test-model", transport=transport))
        self.assertEqual(str(caught.exception), "PROVIDER_UNAVAILABLE")
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.read_calls, 0)
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
