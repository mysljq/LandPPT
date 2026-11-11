"""Reset generated artifacts only while holding the generation lock."""
import time

from sqlalchemy import delete, select

from ...database.models import Project, SlideData, TodoBoard, TodoStage, SpeechScript, NarrationAudio, ProjectVersion


class SlideResetService:
    @staticmethod
    async def reset(session, project_id, user_id):
        async with session.begin():
            project = (await session.execute(select(Project).where(
                Project.project_id == project_id, Project.user_id == user_id
            ).with_for_update())).scalar_one_or_none()
            if project is None:
                return False
            for model in (NarrationAudio, SpeechScript, SlideData, ProjectVersion):
                await session.execute(delete(model).where(model.project_id == project_id))
            project.slides_html = None
            project.slides_data = []
            project.status = "in_progress"
            project.updated_at = time.time()
            stages = (await session.execute(select(TodoStage).where(
                TodoStage.project_id == project_id
            ).order_by(TodoStage.stage_index))).scalars().all()
            creation = next((s for s in stages if s.stage_id == "ppt_creation"), None)
            if creation:
                for stage in stages:
                    if stage.stage_index >= creation.stage_index:
                        stage.status = "pending"
                        stage.progress = 0
                        stage.result = None
                        stage.updated_at = time.time()
                board = (await session.execute(select(TodoBoard).where(
                    TodoBoard.project_id == project_id
                ))).scalar_one_or_none()
                if board:
                    board.current_stage_index = creation.stage_index
                    board.overall_progress = sum(s.progress for s in stages) / max(len(stages), 1)
                    board.updated_at = time.time()
            return True
