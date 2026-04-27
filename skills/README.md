# Project Skills

This repository includes reusable Codex skills under `skills/`.

## Available

- `landppt-skills`
  - Path: `skills/landppt-skills/SKILL.md`
  - Purpose: Independent LandPPT-style workflow for native editable PPTX generation, speaker scripts, narration audio, and explainer video export.
  - Includes:
    - Requirement, outline, prompt, and native PPTX guidance
    - Self-contained local scripts for outline validation, reference PPTX analysis, native template/PPTX generation, narration, and video export
    - No dependency on the LandPPT web service, database, protected routes, commercial conversion services, or HTML slide rendering

- `landppt-ppt-generation`
  - Path: `skills/landppt-ppt-generation/SKILL.md`
  - Purpose: End-to-end LandPPT PPT generation and post-edit operations via user API key.
  - Includes:
    - Full generation workflow runner (`scripts/run_flow.py`)
    - Project operations toolkit (`scripts/project_ops.py`)
    - Curl reference endpoints (`references/endpoints.md`)

## Usage

From Codex:

```text
[$landppt-ppt-generation] 生成一个 12 页、主题为人类何时毁灭的开启联网搜索的 PPT，并返回分享链接
```

Directly (if Python is available):

```bash
python skills/landppt-ppt-generation/scripts/run_flow.py --help
python skills/landppt-ppt-generation/scripts/project_ops.py --help
```

Without Python, use the curl-only endpoint sequence in:

`skills/landppt-ppt-generation/references/endpoints.md`
