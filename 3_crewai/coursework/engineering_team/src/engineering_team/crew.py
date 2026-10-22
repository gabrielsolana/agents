from crewai import Agent, Crew, LLM, Process, Task
# `crew` is aliased: the EngineeringTeam.crew method would otherwise shadow the decorator in the class body.
from crewai.project import CrewBase, agent, task
from crewai.project import crew as crew_decorator
from crewai.agents.agent_builder.base_agent import BaseAgent
from .tools.sandbox_tools import (
    replace_in_sandbox_file, sandbox_tools, ux_tools, write_sandbox_file,
)
from .tools.cost_tools import cost_tools, mark_start, mark_task_done, register_crew
from .tools.release_tools import release_tools, reset_release_flag
# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

# Anthropic's default max_tokens is too low for the long design/code outputs and yields
# empty responses ("Invalid response from LLM call - None or empty").
def _llm(model: str = "anthropic/claude-sonnet-5-5") -> LLM:
    return LLM(model=model, max_tokens=64000)


# Judgment-heavy roles (design, review decisions, UX critique) run on the strongest model.
STRONG_MODEL = "anthropic/claude-fable-5-1"


@CrewBase
class EngineeringTeam():
    """EngineeringTeam crew"""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(
            config=self.agents_config['engineering_lead'],
            llm=_llm(STRONG_MODEL),
            verbose=True,
            tools=ux_tools + cost_tools + release_tools,
            mcps=["https://mcp.context7.com/mcp"]
        )

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['backend_engineer'],
            llm=_llm(),
            verbose=True,
            tools=sandbox_tools
        )
    
    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['frontend_engineer'],
            llm=_llm(),
            verbose=True,
            tools=sandbox_tools,
            mcps=["https://mcp.context7.com/mcp"],
        )
    
    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['test_engineer'],
            llm=_llm(),
            verbose=True,
            tools=sandbox_tools
        )

    @agent
    def ux_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['ux_reviewer'],
            llm=_llm(STRONG_MODEL),
            verbose=True,
            tools=ux_tools
        )

    @agent
    def fiscal_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['fiscal_reviewer'],
            llm=_llm(),
            verbose=True,
            tools=sandbox_tools
        )

    @agent
    def requirements_auditor(self) -> Agent:
        return Agent(
            config=self.agents_config['requirements_auditor'],
            llm=_llm(),
            verbose=True,
            tools=sandbox_tools
        )

    @agent
    def code_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['code_reviewer'],
            llm=_llm(),
            verbose=True,
            tools=ux_tools
        )

    @agent
    def manual_writer(self) -> Agent:
        return Agent(
            config=self.agents_config['manual_writer'],
            llm=_llm(),
            verbose=True,
            tools=ux_tools + [write_sandbox_file, replace_in_sandbox_file]
        )

    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task']
        )

    @task
    def code_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_task'],
        )

    @task
    def frontend_task(self) -> Task:
        return Task(
            config=self.tasks_config['frontend_task'],
        )

    @task
    def ux_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['ux_review_task'],
        )

    @task
    def fiscal_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['fiscal_review_task'],
        )

    @task
    def requirements_audit_task(self) -> Task:
        return Task(
            config=self.tasks_config['requirements_audit_task'],
        )

    @task
    def code_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_review_task'],
        )

    @task
    def review_decision_task(self) -> Task:
        return Task(
            config=self.tasks_config['review_decision_task'],
        )

    @task
    def backend_fix_task(self) -> Task:
        return Task(
            config=self.tasks_config['backend_fix_task'],
        )

    @task
    def ux_revision_task(self) -> Task:
        return Task(
            config=self.tasks_config['ux_revision_task'],
        )

    @task
    def test_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_task'],
        )   

    @task
    def manual_task(self) -> Task:
        return Task(
            config=self.tasks_config['manual_task'],
        )

    @task
    def release_task(self) -> Task:
        return Task(
            config=self.tasks_config['release_task'],
        )

    @task
    def cost_report_task(self) -> Task:
        return Task(
            config=self.tasks_config['cost_report_task'],
        )

    @task
    def apply_decision_task(self) -> Task:
        return Task(
            config=self.tasks_config['apply_decision_task'],
        )

    @task
    def solo_code_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['solo_code_review_task'],
        )

    @task
    def change_design_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_design_task'],
        )

    @task
    def change_code_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_code_task'],
        )

    @task
    def change_frontend_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_frontend_task'],
        )

    @task
    def change_test_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_test_task'],
        )

    @task
    def change_audit_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_audit_task'],
        )

    @task
    def change_release_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_release_task'],
        )

    @task
    def change_manual_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_manual_task'],
        )

    @task
    def change_cost_report_task(self) -> Task:
        return Task(
            config=self.tasks_config['change_cost_report_task'],
        )

    _PIPELINE_PREFIXES = ("change_", "solo_", "apply_")

    def _tasks(self, prefix: str | tuple[str, ...] | None) -> list[Task]:
        """Tasks of one pipeline: those starting with `prefix`, or the new-build ones when prefix is None."""
        if prefix is None:
            return [t for t in self.tasks if not (t.name or "").startswith(self._PIPELINE_PREFIXES)]
        return [t for t in self.tasks if (t.name or "").startswith(prefix)]

    def _build_crew(self, agents: list[BaseAgent], prefix: str | tuple[str, ...] | None) -> Crew:
        the_crew = Crew(
            agents=agents,
            manager_agent=self.engineering_lead(),
            tasks=self._tasks(prefix),
            process=Process.sequential,
            verbose=True,
            tracing=True,
            before_kickoff_callbacks=[mark_start, reset_release_flag],
            task_callback=mark_task_done,
        )
        register_crew(the_crew)
        return the_crew

    @crew_decorator
    def crew(self) -> Crew:
        """Creates the EngineeringTeam crew that builds the application from the requirements"""
        return self._build_crew(
            [
                self.backend_engineer(), self.frontend_engineer(), self.test_engineer(),
                self.ux_reviewer(), self.fiscal_reviewer(), self.requirements_auditor(), self.code_reviewer(), self.manual_writer(),
            ],
            prefix=None,
        )

    @crew_decorator
    def change_crew(self) -> Crew:
        """Creates the crew that applies a change request to the application already in the sandbox"""
        return self._build_crew(
            [
                self.backend_engineer(), self.frontend_engineer(), self.test_engineer(),
                self.requirements_auditor(), self.manual_writer(),
            ],
            prefix="change_",
        )

    @crew_decorator
    def apply_review_crew(self) -> Crew:
        """Creates the crew that applies the findings of a review: the lead filters them, then the change pipeline runs"""
        return self._build_crew(
            [
                self.backend_engineer(), self.frontend_engineer(), self.test_engineer(),
                self.requirements_auditor(), self.manual_writer(),
            ],
            prefix=("apply_", "change_"),
        )

    @crew_decorator
    def review_crew(self) -> Crew:
        """Creates the crew that only reviews the code already in the sandbox"""
        return self._build_crew([self.code_reviewer()], prefix="solo_")
