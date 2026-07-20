from __future__ import annotations

import json

from floppy_backend.services import enterprise_search as es


def test_unauthorized_without_token_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(es, "_token_cache_dir", lambda: tmp_path / "uuap")
    monkeypatch.delenv("SANDBOX_USERNAME", raising=False)
    monkeypatch.delenv("BAIDU_CC_USERNAME", raising=False)
    service = es.EnterpriseSearchService()
    assert service.available is False
    assert service.neisou("食堂在哪") == {"status": "unauthorized", "results": []}


def test_identity_autodetected_from_cache_file(tmp_path, monkeypatch):
    cache = tmp_path / "uuap"
    cache.mkdir()
    (cache / ".eac_ugate_token_zhangsan").write_text(json.dumps({"token": "tok-123"}), encoding="utf-8")
    monkeypatch.setattr(es, "_token_cache_dir", lambda: cache)
    monkeypatch.delenv("SANDBOX_USERNAME", raising=False)
    monkeypatch.delenv("BAIDU_CC_USERNAME", raising=False)
    service = es.EnterpriseSearchService()
    assert service.available is True
    assert service._identity() == ("zhangsan", "tok-123")


def test_extract_results_handles_nested_envelopes():
    payload = {
        "code": 0,
        "data": {
            "list": [
                {"title": "<em>员工餐厅</em>分布指南", "url": "http://ku/x", "summary": "K2 一层<em>食堂</em>营业至 20:00"},
                {"docTitle": "园区平面图", "docUrl": "http://ku/y"},
                {"title": "<em>员工餐厅</em>分布指南", "url": "http://dup"},  # dedup by title
            ]
        },
    }
    results = es._extract_results(payload, limit=3)
    assert [r["title"] for r in results] == ["员工餐厅分布指南", "园区平面图"]
    assert results[0]["snippet"] == "K2 一层食堂营业至 20:00"
    assert results[0]["url"] == "http://ku/x"
