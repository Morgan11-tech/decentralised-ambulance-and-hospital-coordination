import pytest

from models.classification import ClassificationResult, LabelResult

THRESHOLD = 0.70


@pytest.mark.parametrize(
    "label, expected",
    [
        (LabelResult(value="trauma", confidence=0.91), "trauma"),
        (LabelResult(value="trauma", confidence=0.70), "trauma"),  # threshold is inclusive
        (LabelResult(value="trauma", confidence=0.69), "uncertain"),
        (LabelResult(value="trauma", confidence=None), "uncertain"),
        (LabelResult(value="uncertain", confidence=0.99), "uncertain"),
    ],
)
def test_final_value(label, expected):
    assert label.final_value(THRESHOLD) == expected


def test_uncertain_fields_lists_rejected_labels_in_order():
    result = ClassificationResult(
        incident_type=LabelResult(value="trauma", confidence=0.9),
        severity=LabelResult(value="urgent", confidence=0.5),
        consciousness_concern=LabelResult(value="no", confidence=0.95),
        breathing_concern=LabelResult(value="uncertain", confidence=0.8),
    )
    assert result.uncertain_fields(THRESHOLD) == ["severity", "breathing_concern"]


def test_all_confident():
    label = LabelResult(value="yes", confidence=0.99)
    result = ClassificationResult(
        incident_type=LabelResult(value="respiratory", confidence=0.99),
        severity=LabelResult(value="critical", confidence=0.99),
        consciousness_concern=label,
        breathing_concern=label,
    )
    assert result.uncertain_fields(THRESHOLD) == []


def test_unavailable_marks_everything_uncertain():
    result = ClassificationResult.unavailable("Jev HTTP 503")
    assert result.error == "Jev HTTP 503"
    assert len(result.uncertain_fields(THRESHOLD)) == 4
