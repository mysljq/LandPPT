from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "src/landppt/web/route_modules/speech_script_routes.py"
DIALOG_JS_FILE = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.speechScriptsDialog.js"
MANAGE_JS_FILE = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.speechScriptsManage.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_speech_script_progress_has_sse_endpoint():
    route_text = _read(ROUTE_FILE)

    assert '@router.get("/api/projects/{project_id}/speech-scripts/progress/{task_id}/stream")' in route_text
    assert "async def stream_speech_script_progress(" in route_text
    assert 'media_type="text/event-stream"' in route_text
    assert '"X-Accel-Buffering": "no"' in route_text
    assert "event: progress" in route_text
    assert '"done" if progress_info.status in {"completed", "failed"}' in route_text
    assert "event: progress_error" in route_text


def test_speech_script_progress_frontend_uses_sse_with_polling_fallback():
    dialog_text = _read(DIALOG_JS_FILE)
    manage_text = _read(MANAGE_JS_FILE)

    assert "new EventSource(url, { withCredentials: true })" in dialog_text
    assert "/speech-scripts/progress/${taskId}/stream" in dialog_text
    assert "startProgressTrackingPolling(" in dialog_text
    assert "startSingleScriptProgressTrackingPolling(" in dialog_text
    assert "startSpeechHumanizeProgressTrackingPolling(" in manage_text
    assert "typeof startSpeechProgressSse === 'function'" in manage_text
