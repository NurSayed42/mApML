import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from workers.analytics_worker import AnalyticsWorker


@pytest.fixture
def worker():
    return AnalyticsWorker()


def test_compute_scores_high_quality(worker):
    """Test scoring with high-quality content."""
    content = [
        "This marketing strategy targets young professionals aged 25-35. "
        "Our unique value proposition differentiates us from competitors. "
        "The competitive advantage lies in our innovative approach to customer engagement. "
        "Call to action: Get started today and sign up for a free trial. "
        "B2B strategy with ROI-focused recommendations. Target audience: small business owners. "
        "Revenue growth strategy with market analysis and customer segment insights. " * 3
    ]
    scores = worker._compute_scores(content)
    total = sum(scores.values())
    assert total >= 60, f"High quality content should score >= 60, got {total}"
    assert scores["call_to_action"] == 20
    assert scores["audience_specificity"] > 0
    assert scores["competitive_differentiation"] > 0


def test_compute_scores_low_quality(worker):
    """Test scoring with low-quality content."""
    content = ["Hello world"]
    scores = worker._compute_scores(content)
    total = sum(scores.values())
    assert total <= 20, f"Low quality content should score <= 20, got {total}"
    assert scores["content_length"] <= 5
    assert scores["call_to_action"] == 0


def test_get_category_high(worker):
    assert worker._get_category(75) == "High"
    assert worker._get_category(70) == "High"
    assert worker._get_category(100) == "High"


def test_get_category_medium(worker):
    assert worker._get_category(50) == "Medium"
    assert worker._get_category(40) == "Medium"
    assert worker._get_category(69) == "Medium"


def test_get_category_low(worker):
    assert worker._get_category(20) == "Low"
    assert worker._get_category(0) == "Low"
    assert worker._get_category(39) == "Low"


def test_parse_recommendations_valid_json(worker):
    """Test parsing valid JSON recommendations."""
    log = MagicMock()
    recs = [
        {"title": "Rec 1", "rationale": "Why", "action": "Do this"},
        {"title": "Rec 2", "rationale": "Because", "action": "Do that"},
        {"title": "Rec 3", "rationale": "Important", "action": "Do other"},
    ]
    result = worker._parse_recommendations(json.dumps(recs), log)
    assert len(result) == 3
    assert result[0]["title"] == "Rec 1"


def test_parse_recommendations_invalid_json_returns_defaults(worker):
    """Test fallback recommendations on parse failure."""
    log = MagicMock()
    result = worker._parse_recommendations("Not JSON at all!!!", log)
    assert len(result) == 3
    assert all("title" in r for r in result)
    assert all("action" in r for r in result)


def test_parse_recommendations_markdown_json(worker):
    """Test parsing recommendations wrapped in markdown."""
    log = MagicMock()
    recs = [{"title": "T1", "rationale": "R1", "action": "A1"}]
    markdown = f"```json\n{json.dumps(recs)}\n```"
    result = worker._parse_recommendations(markdown, log)
    assert len(result) == 1


def test_score_length_thresholds(worker):
    """Test content length scoring at different thresholds."""
    # Under 50 words
    scores_tiny = worker._compute_scores(["tiny"])
    assert scores_tiny["content_length"] == 0

    # 50-150 words
    medium_content = " ".join(["word"] * 80)
    scores_medium = worker._compute_scores([medium_content])
    assert scores_medium["content_length"] == 5

    # 150-300 words
    decent_content = " ".join(["word"] * 200)
    scores_decent = worker._compute_scores([decent_content])
    assert scores_decent["content_length"] == 10

    # 300-500 words
    good_content = " ".join(["word"] * 350)
    scores_good = worker._compute_scores([good_content])
    assert scores_good["content_length"] == 15

    # 500+ words
    great_content = " ".join(["word"] * 600)
    scores_great = worker._compute_scores([great_content])
    assert scores_great["content_length"] == 20


@pytest.mark.asyncio
async def test_process_full_flow(worker):
    """Test full analytics process flow."""
    log = MagicMock()
    message = {
        "task_id": "task-123",
        "dag_node_id": "node-abc",
        "user_id": "user-456",
        "correlation_id": "corr-789",
        "task_type": "marketing_strategy",
        "payload": {"instruction": "Coffee shop marketing"},
    }

    mock_outputs = [
        "Market research shows growing demand for specialty coffee. "
        "Target audience: young professionals. Unique value proposition. "
        "Competitive differentiation strategy. Revenue growth. "
        "Call to action: Sign up now for exclusive offers." * 5
    ]

    with patch.object(worker, "_collect_all_outputs", new_callable=AsyncMock, return_value=mock_outputs), \
         patch.object(worker, "call_gemini", new_callable=AsyncMock) as mock_gemini, \
         patch("workers.analytics_worker.get_or_create_collection") as mock_chroma, \
         patch("workers.analytics_worker.embed_text", return_value=[0.1] * 384):

        mock_gemini.return_value = json.dumps([
            {"title": "Expand digital", "rationale": "Growth", "action": "Invest in SEO"},
            {"title": "Partner up", "rationale": "Network", "action": "Find local partners"},
            {"title": "Loyalty program", "rationale": "Retention", "action": "Create rewards"},
        ])

        mock_col = MagicMock()
        mock_chroma.return_value = mock_col

        result = await worker.process(message, log)

    assert "analytics_report" in result
    assert result["analytics_report"]["engagement_score"] >= 0
    assert len(result["analytics_report"]["recommendations"]) == 3
    assert result["chroma_doc_id"].startswith("analytics_")
