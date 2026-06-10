from __future__ import annotations

from .agents import AnalystAgent, ExecutorAgent, ManagerAgent, ResearchAgent, ReviewerAgent, WriterAgent
from .models import CrewTask
from .templates import get_template


class AgentCrewRuntime:
    def __init__(self) -> None:
        self.manager = ManagerAgent()
        self.researcher = ResearchAgent()
        self.analyst = AnalystAgent()
        self.writer = WriterAgent()
        self.reviewer = ReviewerAgent()
        self.executor = ExecutorAgent()

    def run(self, template_id: str, goal: str) -> CrewTask:
        template = get_template(template_id)
        task = CrewTask(template_id=template_id, title=template.name, goal=goal.strip() or template.example_goal)
        task.status = "running"

        self.manager.run(task)
        research = self.researcher.run(task)
        analysis = self.analyst.run(task, research)
        self.writer.run(task, research, analysis)
        self.reviewer.run(task, research)
        self.executor.run(task)
        return task

