from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from .tools.sandbox_tools import sandbox_tools, ux_tools
from .tools.cost_tools import cost_tools, mark_start, mark_task_done, register_crew
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
            tools=ux_tools + cost_tools,
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
    def manual_writer(self) -> Agent:
        return Agent(
            config=self.agents_config['manual_writer'],
            llm=_llm(),
            verbose=True,
            tools=ux_tools
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
    def cost_report_task(self) -> Task:
        return Task(
            config=self.tasks_config['cost_report_task'],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the EngineeringTeam crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        the_crew = Crew(
            agents=[
                self.backend_engineer(), self.frontend_engineer(), self.test_engineer(),
                self.ux_reviewer(), self.fiscal_reviewer(), self.requirements_auditor(), self.manual_writer(),
            ],
            manager_agent=self.engineering_lead(),
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
            tracing=True,
            before_kickoff_callbacks=[mark_start],
            task_callback=mark_task_done,
        )
        register_crew(the_crew)
        return the_crew
