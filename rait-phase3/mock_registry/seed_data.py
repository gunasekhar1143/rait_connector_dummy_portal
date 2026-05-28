"""Seed constants for registry.db. metric_name values must match rait_connector Metric enum strings."""

SEED_DIMENSIONS = [
    # (dimension_id, dimension_name, aggregation_strategy, safety_threshold, display_order)
    ("dim-bias-001", "Bias & Fairness",                  "weighted_scorecard", 0.5, 1),
    ("dim-expl-001", "Explainability & Transparency",    "average",            0.5, 2),
    ("dim-sec-001",  "Security & Adversarial Robustness","min_gate",           0.5, 3),
]

SEED_METRICS = [
    # (metric_id, metric_name, description)
    ("met-hate-001", "Hate and Unfairness (Azure)",  "Bias detection via Azure AI"),
    ("met-coh-001",  "Coherence (Azure)",            "Response coherence via Azure OpenAI"),
    ("met-vuln-001", "Code Vulnerability (Azure)",   "Code security evaluation via Azure AI"),
]

SEED_DIMENSION_METRICS = [
    # (dimension_id, metric_id, weight, risk_tier)
    ("dim-bias-001", "met-hate-001", 0.7, "high_risk"),
    ("dim-expl-001", "met-coh-001",  1.0, "standard"),
    ("dim-sec-001",  "met-vuln-001", 1.0, "standard"),
]
