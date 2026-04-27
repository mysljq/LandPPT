from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NARRATION_ROUTES = ROOT / "src/landppt/web/route_modules/narration_routes.py"
EXPORT_ROUTES = ROOT / "src/landppt/web/route_modules/export_routes.py"
BACKGROUND_TASKS = ROOT / "src/landppt/services/background_tasks.py"
NARRATION_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectEditorNarration.js"
SPEECH_MANAGE_JS = ROOT / "src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.speechScriptsManage.js"
SETTINGS_TEMPLATE = ROOT / "src/landppt/web/templates/components/settings/ai_config/content_1.html"
NARRATION_SERVICE = ROOT / "src/landppt/services/narration_service.py"
DB_CONFIG_SERVICE = ROOT / "src/landppt/services/db_config_service.py"
TEMPLATE_FILE = ROOT / "src/landppt/web/templates/pages/project/project_slides_editor.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_narration_audio_export_route_and_download_support_are_wired():
    narration_routes_text = _read(NARRATION_ROUTES)
    export_routes_text = _read(EXPORT_ROUTES)
    background_tasks_text = _read(BACKGROUND_TASKS)

    assert '@router.post("/api/projects/{project_id}/export/narration-audio")' in narration_routes_text
    assert "async def export_narration_audio(" in narration_routes_text
    assert 'task_type="narration_audio_export"' in narration_routes_text
    assert '"audio_path": zip_path' in narration_routes_text
    assert "narration_audio_export" in background_tasks_text
    assert "narration_audio_export" in export_routes_text
    assert '"audio_path"' in export_routes_text
    assert "X-Export-Method\": \"Narration-Audio\"" in export_routes_text


def test_narration_generation_progress_updates_are_wired():
    narration_routes_text = _read(NARRATION_ROUTES)
    narration_service_text = _read(NARRATION_SERVICE)

    assert 'task_id = task_manager.create_task(\n            "narration_generation"' in narration_routes_text
    assert "async_task = asyncio.create_task(task_manager.execute_task(task_id, narration_task))" in narration_routes_text
    assert "task_id_holder" not in narration_routes_text
    assert "async def update_audio_progress(done_count: int, total_count: int)" in narration_routes_text
    assert "progress_callback=update_audio_progress" in narration_routes_text
    assert "progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None" in narration_service_text
    assert "await progress_callback(done_count, total_count)" in narration_service_text
    assert "await mark_done()" in narration_service_text


def test_narration_audio_export_ui_is_wired():
    narration_js_text = _read(NARRATION_JS)
    speech_manage_js_text = _read(SPEECH_MANAGE_JS)
    template_text = _read(TEMPLATE_FILE)

    assert "async function exportNarrationAudio()" in narration_js_text
    assert "/export/narration-audio" in narration_js_text
    assert "triggerFileDownload(downloadUrl)" in narration_js_text
    assert "导出讲解音频" in speech_manage_js_text
    assert 'onclick="exportNarrationAudio()"' in speech_manage_js_text
    assert "projectEditorNarration.js?v=20260509-custom-tts-api-v1" in template_text
    assert "projectSlidesEditor.speechScriptsManage.js?v=20260509-custom-tts-api-v1" in template_text


def test_xiaomimimo_tts_provider_is_wired():
    narration_service_text = _read(NARRATION_SERVICE)
    narration_routes_text = _read(NARRATION_ROUTES)
    narration_js_text = _read(NARRATION_JS)
    speech_manage_js_text = _read(SPEECH_MANAGE_JS)
    settings_template_text = _read(SETTINGS_TEMPLATE)
    db_config_text = _read(DB_CONFIG_SERVICE)

    assert '"xiaomimimo"' in narration_service_text
    assert "_generate_project_slide_audios_xiaomimimo" in narration_service_text
    assert "mimo-v2.5-tts-voicedesign" in narration_service_text
    assert "mimo-v2.5-tts-voiceclone" in narration_service_text
    assert '"api-key": api_key' in narration_service_text
    assert '"voice": ref_voice_data_uri' in narration_service_text
    assert "reference_audio_path=reference_audio_path" in narration_service_text
    assert "ref={ref_hash}" in narration_service_text
    assert "voice_prompt: str = \"\"" in narration_routes_text
    assert "voice_prompt=(request.voice_prompt or \"\")" in narration_routes_text
    assert '<option value="xiaomimimo"' in speech_manage_js_text
    assert "narrationMimoMode" in speech_manage_js_text
    assert "voiceclone" in speech_manage_js_text
    assert "narrationMimoVoicePrompt" in speech_manage_js_text
    assert "getNarrationMimoVoicePrompt()" in narration_js_text
    assert "narrationNeedsReferenceAudio(provider)" in narration_js_text
    assert "mimo_api_key" in db_config_text
    assert "mimo_tts_clone_model" in db_config_text
    assert "mimo_tts_clone_model" in settings_template_text
    assert "mimo_tts_voice_prompt" in settings_template_text


def test_custom_tts_api_provider_is_wired():
    narration_service_text = _read(NARRATION_SERVICE)
    speech_manage_js_text = _read(SPEECH_MANAGE_JS)
    settings_template_text = _read(SETTINGS_TEMPLATE)
    db_config_text = _read(DB_CONFIG_SERVICE)

    assert '"custom_tts_api"' in narration_service_text
    assert "_generate_project_slide_audios_custom_tts_api" in narration_service_text
    assert "custom_tts_api_url" in narration_service_text
    assert '"text": text' in narration_service_text
    assert '"speaker": speaker' in narration_service_text
    assert '"instruct": instruct' not in narration_service_text
    assert '"speed": speed' in narration_service_text
    assert '"lang": api_lang' not in narration_service_text
    assert '"novasr": novasr' in narration_service_text
    assert "TOM女" in narration_service_text
    assert '<option value="custom_tts_api"' in speech_manage_js_text
    assert "custom_tts_api_url" in db_config_text
    assert "custom_tts_api_speaker" in settings_template_text
    assert "custom_tts_api_instruct" not in settings_template_text
    assert "custom_tts_api_lang" not in settings_template_text
