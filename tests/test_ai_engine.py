"""Tests for the Gemini engine: parsing, validation and retry logic.

All network interaction is stubbed out - no API key or connectivity needed.
"""

import json

import pytest

from core.config import Config
import core.ai_engine as ai_engine_module
from core.ai_engine import GeminiEngine


@pytest.fixture()
def engine(monkeypatch):
    """GeminiEngine with a fake key (constructor makes no network calls)."""
    monkeypatch.setattr(Config, 'GOOGLE_API_KEY', 'test-key', raising=True)
    return GeminiEngine()


class FakeModel:
    """GenerativeModel stand-in with programmable failure behaviour."""

    def __init__(self, responses=None, fail_times=0):
        self.responses = list(responses or [])
        self.fail_times = fail_times
        self.calls = []

    def generate_content(self, content, generation_config=None):
        self.calls.append(content)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError('simulated API outage')
        if self.responses:
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        raise AssertionError('no scripted response left')


class _Response:
    def __init__(self, text):
        self.text = text


@pytest.fixture()
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ai_engine_module.time, 'sleep', lambda s: sleeps.append(s))
    return sleeps


class TestCleanJsonResponse:
    def test_json_code_fence(self, engine):
        assert engine._clean_json_response('```json\n[1, 2]\n```') == '[1, 2]'

    def test_plain_code_fence(self, engine):
        assert engine._clean_json_response('```\n{"a": 1}\n```') == '{"a": 1}'

    def test_bare_text_untouched(self, engine):
        assert engine._clean_json_response('  [1]  ') == '[1]'


class TestParseDocument:
    def _png(self, tmp_path):
        from PIL import Image
        path = tmp_path / 'invoice.png'
        Image.new('RGB', (10, 10)).save(path)
        return path

    def test_image_flow_validates_and_normalizes(self, engine, monkeypatch, tmp_path):
        raw = json.dumps([
            {'item_name': '  Heavy Cream  ', 'price': '24.50', 'unit': 'Case'},
            {'item_name': 'No Price Item'},               # dropped: missing price
            {'price': 5.0},                                # dropped: missing name
        ])
        captured = {}
        monkeypatch.setattr(
            engine, '_call_with_retry',
            lambda model, content, generation_config=None: captured.update(content=content) or raw
        )

        items = engine.parse_document(self._png(tmp_path), vendor_hint='Sysco')

        assert len(items) == 1
        assert items[0]['item_name'] == 'Heavy Cream'
        assert items[0]['price'] == 24.50
        assert items[0]['vendor'] == 'Sysco'          # from vendor_hint
        # Prompt plus one PIL image part
        assert len(captured['content']) == 2

    def test_pdf_sent_as_inline_bytes_not_pil(self, engine, monkeypatch, tmp_path):
        pdf_bytes = b'%PDF-1.4 fake-for-test'
        pdf_path = tmp_path / 'price_list.pdf'
        pdf_path.write_bytes(pdf_bytes)

        captured = {}
        monkeypatch.setattr(
            engine, '_call_with_retry',
            lambda model, content, generation_config=None: captured.update(content=content) or '[]'
        )

        items = engine.parse_document(pdf_path)

        assert items == []
        part = captured['content'][1]
        assert part['mime_type'] == 'application/pdf'
        assert part['data'] == pdf_bytes

    def test_missing_file_raises(self, engine, tmp_path):
        with pytest.raises(FileNotFoundError):
            engine.parse_document(tmp_path / 'ghost.png')

    def test_invalid_json_returns_empty_list(self, engine, monkeypatch, tmp_path):
        monkeypatch.setattr(engine, '_call_with_retry',
                            lambda model, content, generation_config=None: 'not json at all')
        assert engine.parse_document(self._png(tmp_path)) == []


class TestRetryBehaviour:
    def test_retries_then_succeeds(self, engine, no_sleep):
        model = FakeModel(fail_times=2, responses=[_Response('ok')])
        assert engine._call_with_retry(model, 'prompt') == 'ok'
        assert no_sleep == [2, 4]  # exponential backoff: delay * 2**attempt

    def test_raises_after_max_retries(self, engine, no_sleep):
        model = FakeModel(fail_times=99)
        with pytest.raises(Exception, match='3 attempts'):
            engine._call_with_retry(model, 'prompt')
        assert len(model.calls) == 3


class TestValidateExtractedPrices:
    def test_falls_back_to_originals_on_bad_json(self, engine, monkeypatch):
        prices = [{'item_name': 'Flour', 'price': 18.0, 'unit': 'Bag'}]
        monkeypatch.setattr(engine, '_call_with_retry',
                            lambda model, content, generation_config=None: '{{{')
        result = engine.validate_extracted_prices(prices)

        assert result == prices
        assert result[0]['confidence'] == 0.8

    def test_passes_through_validated_list(self, engine, monkeypatch):
        validated = [{'item_name': 'Flour', 'price': 18.0, 'confidence': 0.95}]
        monkeypatch.setattr(engine, '_call_with_retry',
                            lambda model, content, generation_config=None: json.dumps(validated))
        assert engine.validate_extracted_prices([{'item_name': 'flour', 'price': 18.0}]) == validated

    def test_empty_input_short_circuits(self, engine):
        assert engine.validate_extracted_prices([]) == []
