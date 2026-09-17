from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TODO_EDITOR_BODY = (
    ROOT
    / "src"
    / "landppt"
    / "web"
    / "templates"
    / "components"
    / "project"
    / "todo_board_with_editor"
    / "body_1.html"
)


def test_free_template_modal_is_hidden_without_bootstrap_css():
    """The optional wizard must not leak into the generation page's document flow."""
    source = TODO_EDITOR_BODY.read_text(encoding="utf-8")

    assert '.ftm-modal:not(.show) { display: none !important; }' in source
    assert (
        'id="freeTemplateModal" tabindex="-1" aria-hidden="true" style="display:none;"'
        in source
    )
