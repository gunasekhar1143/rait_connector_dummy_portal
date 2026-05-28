from deepeval.metrics import BiasMetric
from deepeval.test_case import LLMTestCase

def evaluate(prompt, response):

    metric = BiasMetric(threshold=0.5)

    test_case = LLMTestCase(
        input=prompt,
        actual_output=response
    )

    metric.measure(test_case)

    return {
        "bias_score": metric.score,
        "reason": metric.reason
    }