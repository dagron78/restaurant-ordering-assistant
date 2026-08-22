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
    """F-14: validation is deterministic - no LLM round-trip that could
    write hallucinated corrections back into the price table."""

    def test_keeps_clean_rows_and_normalizes(self, engine):
        raw = [
            {'item_name': '  Flour ', 'price': '18.00', 'unit': ' Bag '},
        ]
        result = engine.validate_extracted_prices(raw)

        assert result == [{
            'item_name': 'Flour',
            'price': 18.0,
            'unit': 'Bag',
            'vendor': 'Unknown',
            'confidence': 1.0,
        }]

    def test_drops_missing_or_unparseable_prices(self, engine):
        raw = [
            {'item_name': 'No Price'},
            {'item_name': 'Bad Price', 'price': 'abc'},
            {'price': 5.0},                      # no name
        ]
        assert engine.validate_extracted_prices(raw) == []

    def test_drops_out_of_bounds_prices(self, engine):
        raw = [
            {'item_name': 'Free', 'price': 0},
            {'item_name': 'Negative', 'price': -3.0},
            {'item_name': 'Absurd', 'price': 999_999.0},
            {'item_name': 'Fine', 'price': 12.5},
        ]
        result = engine.validate_extracted_prices(raw)
        assert [r['item_name'] for r in result] == ['Fine']

    def test_dedupes_identical_lines(self, engine):
        raw = [
            {'item_name': 'Flour', 'price': 18.0, 'unit': 'Bag', 'vendor': 'Sysco'},
            {'item_name': 'flour', 'price': 18.0, 'unit': 'bag', 'vendor': 'SYSCO'},
        ]
        assert len(engine.validate_extracted_prices(raw)) == 1

    def test_confidence_is_clamped(self, engine):
        raw = [{'item_name': 'Flour', 'price': 1.0, 'confidence': 5}]
        assert engine.validate_extracted_prices(raw)[0]['confidence'] == 1.0

    def test_makes_no_api_calls(self, engine, monkeypatch):
        """The whole point: validation must not depend on the model."""
        def boom(*args, **kwargs):
            raise AssertionError('validate_extracted_prices must not call the API')

        monkeypatch.setattr(engine, '_call_with_retry', boom)
        engine.validate_extracted_prices([{'item_name': 'X', 'price': 2}])

    def test_empty_input(self, engine):
        assert engine.validate_extracted_prices([]) == []
