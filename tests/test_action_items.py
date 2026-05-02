import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.action_items import (
    generate_action_items,
    load_memory_slices,
    _parse_and_validate,
)


def _per_item(url: str = "https://l.com/p/x") -> dict:
    return {
        "title": "Build vs Buy",
        "publication": "Lenny",
        "author": "Lenny",
        "url": url,
        "one_liner": "Buy non-core, build core",
        "summary": "x" * 100,
        "key_takeaways": ["a", "b"],
    }


def _aggregate() -> dict:
    return {
        "narrative": "x" * 200,
        "cross_cutting_themes": ["theme one"],
        "notable_quotes": [],
    }


def _ok_response(urls: list[str]) -> str:
    return json.dumps({
        "items": [
            {
                "title": f"Action {i+1}",
                "description": f"Do thing {i+1} because of project Y",
                "source_url": urls[i % len(urls)],
                "estimated_minutes": 15 + i * 5,
            }
            for i in range(3)
        ]
    })


def _mock_claude(client_cls, response_texts):
    client = MagicMock()
    responses = []
    for text in response_texts:
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        resp.stop_reason = "end_turn"
        responses.append(resp)
    client.messages.create.side_effect = responses
    client_cls.return_value = client
    return client


@pytest.fixture
def memory_slices():
    return {"role": "PM at Acme", "projects": "Port templates, GH workflows"}


class TestLoadMemorySlices:
    def test_reads_role_and_projects(self, tmp_path):
        role_path = tmp_path / "role.md"
        projects_path = tmp_path / "projects.md"
        role_path.write_text("# Role\nPM at Acme")
        projects_path.write_text("# Projects\nPort, GH")
        slices = load_memory_slices(role_path=role_path, projects_path=projects_path)
        assert "PM at Acme" in slices["role"]
        assert "Port" in slices["projects"]

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_memory_slices(
                role_path=tmp_path / "missing.md",
                projects_path=tmp_path / "missing2.md",
            )


class TestGenerateActionItems:
    @patch("src.action_items.anthropic.Anthropic")
    def test_returns_3_items_with_valid_urls(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1", "https://b.com/p/2"]
        per_item = [_per_item(u) for u in urls]
        _mock_claude(anthropic_cls, [_ok_response(urls)])

        items = generate_action_items(per_item, _aggregate(), memory_slices)
        assert len(items) == 3
        for item in items:
            assert item["source_url"] in urls
            assert 10 <= item["estimated_minutes"] <= 30
            assert item["title"]
            assert item["description"]

    @patch("src.action_items.anthropic.Anthropic")
    def test_retries_on_invalid_url(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1"]
        per_item = [_per_item(urls[0])]
        bad = json.dumps({"items": [{
            "title": "x", "description": "x",
            "source_url": "https://hallucinated.com/p/z",
            "estimated_minutes": 20,
        }] * 3})
        _mock_claude(anthropic_cls, [bad, _ok_response(urls)])
        items = generate_action_items(per_item, _aggregate(), memory_slices)
        assert all(i["source_url"] in urls for i in items)

    @patch("src.action_items.anthropic.Anthropic")
    def test_retries_on_wrong_count(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1"]
        per_item = [_per_item(urls[0])]
        bad = json.dumps({"items": [{
            "title": "x", "description": "x",
            "source_url": urls[0], "estimated_minutes": 20,
        }] * 5})  # 5 items instead of 3
        _mock_claude(anthropic_cls, [bad, _ok_response(urls)])
        items = generate_action_items(per_item, _aggregate(), memory_slices)
        assert len(items) == 3

    @patch("src.action_items.anthropic.Anthropic")
    def test_retries_on_out_of_range_minutes(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1"]
        per_item = [_per_item(urls[0])]
        bad = json.dumps({"items": [{
            "title": "x", "description": "x",
            "source_url": urls[0], "estimated_minutes": 90,  # > 30
        }] * 3})
        _mock_claude(anthropic_cls, [bad, _ok_response(urls)])
        items = generate_action_items(per_item, _aggregate(), memory_slices)
        assert all(10 <= i["estimated_minutes"] <= 30 for i in items)

    @patch("src.action_items.anthropic.Anthropic")
    def test_raises_after_retry_exhausted(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1"]
        per_item = [_per_item(urls[0])]
        _mock_claude(anthropic_cls, ["not json", "still bad"])
        with pytest.raises(ValueError):
            generate_action_items(per_item, _aggregate(), memory_slices)

    @patch("src.action_items.anthropic.Anthropic")
    def test_injects_memory_slices_into_prompt(self, anthropic_cls, memory_slices):
        urls = ["https://a.com/p/1"]
        per_item = [_per_item(urls[0])]
        client = _mock_claude(anthropic_cls, [_ok_response(urls)])
        generate_action_items(per_item, _aggregate(), memory_slices)
        call_kwargs = client.messages.create.call_args.kwargs
        assert "PM at Acme" in call_kwargs["system"]
        assert "Port templates" in call_kwargs["system"]


class TestParseAndValidate:
    def test_rejects_non_string_minutes(self):
        valid_urls = {"https://x.com"}
        bad = json.dumps({"items": [{
            "title": "x", "description": "x",
            "source_url": "https://x.com",
            "estimated_minutes": "20",  # string, not int
        }] * 3})
        assert _parse_and_validate(bad, valid_urls) is None

    def test_rejects_empty_title(self):
        valid_urls = {"https://x.com"}
        bad = json.dumps({"items": [{
            "title": "", "description": "x",
            "source_url": "https://x.com",
            "estimated_minutes": 20,
        }] * 3})
        assert _parse_and_validate(bad, valid_urls) is None
