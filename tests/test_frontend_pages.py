"""Every Streamlit page must actually load.

The Contract Review page once died with a SyntaxError before rendering anything:
Streamlit's "magic" wraps bare expression statements in st.write, and its AST
pass could not parse a multi-line ternary. The suite passed 191 tests while the
feature was unreachable, because nothing in it ever executed a page.
"""

import contextlib
import pathlib
from unittest.mock import patch

import pytest


@contextlib.contextmanager
def offline():
    """Drive the page without Groq or Qdrant.

    The page is expected to work with both down -- that is what the in-process
    mode is for -- and a test that reaches the network takes 37 seconds and fails
    for reasons unrelated to the code.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "src.agents.procurement_nodes.narrator.ChatGroq",
                side_effect=RuntimeError("Groq unreachable"),
            )
        )
        stack.enter_context(
            patch(
                "src.core.vector_store.vector_store.hybrid_search",
                side_effect=RuntimeError("no qdrant"),
            )
        )
        yield

PAGES = [
    "frontend/app.py",
    "frontend/pages/1_\u2696\ufe0f_Scenario_Analysis.py",
    "frontend/pages/2_\U0001f4c4_Contract_Review.py",
    "frontend/pages/3_\U0001f4d0_Policy_Library.py",
    "frontend/pages/4_\U0001f9fe_Award_Review.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_every_streamlit_page_loads(page):
    from streamlit.testing.v1 import AppTest

    # AppTest resolves a relative path against the calling file, which is this
    # test, not the repo root.
    root = pathlib.Path(__file__).resolve().parent.parent
    app = AppTest.from_file(str(root / page), default_timeout=120).run()
    assert not app.exception, [e.value for e in app.exception]


def test_the_award_review_page_actually_reviews_an_event():
    """Loading is not the same as working.

    The page once rendered perfectly and produced nothing, because "the page
    loads" is all the smoke test above checks. This drives the real path: load a
    sample, run the in-process pipeline, and confirm the summary strip populated.
    """
    from streamlit.testing.v1 import AppTest

    root = pathlib.Path(__file__).resolve().parent.parent
    page = root / "frontend/pages/4_\U0001f9fe_Award_Review.py"
    with offline():
        app = AppTest.from_file(str(page), default_timeout=180).run()

        sample = [b for b in app.button if "Conveyor" in b.label]
        assert sample, [b.label for b in app.button]
        app = sample[0].click().run()
        assert len(app.text_area[0].value) > 500

        if app.radio:
            app = app.radio[0].set_value("Direct (in-process)").run()
        run = [b for b in app.button if "Review this award" in b.label][0]
        app = run.click().run()

    assert not app.exception, [e.value for e in app.exception]
    assert any("Review complete" in s.value for s in app.success)

    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Outcome"] == "Breaches found"
    assert int(metrics["Breaches"]) > 0


def test_a_statute_only_review_shows_the_statute_only_cap():
    """With no policy selected the page must not report a confident clean result."""
    from streamlit.testing.v1 import AppTest

    root = pathlib.Path(__file__).resolve().parent.parent
    page = root / "frontend/pages/4_\U0001f9fe_Award_Review.py"
    with offline():
        app = AppTest.from_file(str(page), default_timeout=180).run()
        sample = [b for b in app.button if "Clean" in b.label][0]
        app = sample.click().run()
        if app.radio:
            app = app.radio[0].set_value("Direct (in-process)").run()
        app = [b for b in app.button if "Review this award" in b.label][0].click().run()

    assert not app.exception, [e.value for e in app.exception]
    confidence = float({m.label: m.value for m in app.metric}["Confidence"])
    assert confidence <= 0.70, "a statute-only review must carry the statute-only cap"
