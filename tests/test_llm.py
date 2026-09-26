from artmirror.services.llm import _extract_score_json


def test_extract_score_json_recovers_missing_dimension_closure():
    content = '''```json
{
  "score": 91,
  "reason": "整体优秀。",
  "dimensions": {
    "构图": {"score": 95, "comment": "构图稳定。"},
    "光影": {"score": 94, "comment": "光线柔和。"},
    "主体与主题": {"score": 96, "comment": "主题明确。"},
    "细节与完成度": {"score": 88, "comment": "细节完整。",
    "色彩与影调": {"score": 92, "comment": "色彩协调。"},
    "美感与艺术性": {"score": 95, "comment": "审美突出。"},
    "技术质量": {"score": 87, "comment": "画质清晰。"}
  }
}
```'''

    result = _extract_score_json(content)

    assert result["score"] == 91
    assert len(result["dimensions"]) == 7
    assert result["dimensions"]["色彩与影调"]["score"] == 92
    assert "色彩与影调" not in result["dimensions"]["细节与完成度"]


def test_extract_score_json_parses_valid_fenced_json():
    result = _extract_score_json('```json\n{"score": 90, "dimensions": {}}\n```')

    assert result["score"] == 90
