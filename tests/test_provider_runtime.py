from scripts.provider_runtime import resolve_codex_model, select_default_codex_model


def test_select_default_codex_model_prefers_latest_spark() -> None:
    models = [
        "gpt-5.2-codex",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.3-codex-mini",
    ]
    assert select_default_codex_model(models) == "gpt-5.3-codex-spark"


def test_resolve_codex_model_alias_spark() -> None:
    models = ["gpt-5.3-codex", "gpt-5.3-codex-spark"]
    assert resolve_codex_model("spark", models) == "gpt-5.3-codex-spark"
