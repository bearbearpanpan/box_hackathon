"""
ObservabilityStack — CloudWatch dashboard + baseline alarms for Reality Check.

Visualizes three things operations actually watches:
  1. Lambda service health (invocations, errors, throttles, duration, concurrency)
  2. External dependencies (Box AI + Bedrock usage, failures, token spend)
  3. The agentic-workflow KPIs (outcomes, human-in-the-loop rate, risk mix)

Custom metrics live in the "RealityCheck" namespace and are emitted as EMF by
box/telemetry.py when the Lambda runs with EMIT_METRICS=true. AWS/Lambda metrics
are published automatically by the service.

The dashboard is intentionally succinct: three rows of three widgets, each
answering one operational question.
"""
from __future__ import annotations

from typing import List, Optional

from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
)
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

NAMESPACE = "RealityCheck"

# Lambda's configured timeout (agent/infra/setup.md: --timeout 60).
LAMBDA_TIMEOUT_MS = 60_000

# Consistent colors so risk/outcome semantics read the same across widgets.
GREEN = "#2ca02c"
AMBER = "#ff7f0e"
RED = "#d62728"
BLUE = "#1f77b4"
PURPLE = "#9467bd"
BROWN = "#8c564b"
PINK = "#e377c2"


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        function_name: str,
        dashboard_name: str = "RealityCheck",
        alarm_email: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.function_name = function_name
        lambda_dims = {"FunctionName": function_name}

        # --- Optional alarm notifications -------------------------------
        alarm_topic: Optional[sns.Topic] = None
        if alarm_email:
            alarm_topic = sns.Topic(self, "AlarmTopic",
                                    display_name=f"{dashboard_name} alarms")
            alarm_topic.add_subscription(subs.EmailSubscription(alarm_email))

        # --- Baseline operational alarms --------------------------------
        self._build_alarms(lambda_dims, alarm_topic)

        # --- Dashboard ---------------------------------------------------
        dashboard = cw.Dashboard(
            self,
            "OpsDashboard",
            dashboard_name=dashboard_name,
            default_interval=Duration.hours(3),
        )

        dashboard.add_widgets(
            cw.TextWidget(
                markdown=(
                    f"# Reality Check - Ops & Utilization\n"
                    f"Lambda **`{function_name}`** - region **`{self.region}`** - "
                    f"custom metrics namespace **`{NAMESPACE}`** "
                    "(emitted when the Lambda runs with `EMIT_METRICS=true`).\n\n"
                    "**Row 1 - Service health** (is the function healthy?) &nbsp;|&nbsp; "
                    "**Row 2 - Dependencies** (Box AI + Bedrock usage/cost) &nbsp;|&nbsp; "
                    "**Row 3 - Workflow KPIs** (what the agent decided)."
                ),
                width=24,
                height=3,
            )
        )

        # Row 1 — Lambda health. Each widget pairs a labelled graph with a short
        # "what/why" caption so an on-call reader needs no external doc.
        dashboard.add_widgets(
            self._lambda_invocations_widget(lambda_dims),
            self._lambda_duration_widget(lambda_dims),
            self._lambda_concurrency_widget(lambda_dims),
        )
        dashboard.add_widgets(
            self._caption(
                "**Invocations / Errors / Throttles**",
                "Traffic and failure volume. Errors > 0 or any throttles means "
                "the function is dropping work - investigate.",
            ),
            self._caption(
                "**Duration p50 / p99 vs 60s timeout**",
                "Request latency. p99 riding the red 60s line means runs are "
                "about to time out (often slow Box AI calls).",
            ),
            self._caption(
                "**Max concurrent executions**",
                "Parallelism in use. Approaching the account concurrency limit "
                "risks throttling; informs reserved-concurrency sizing.",
            ),
        )

        # Row 2 — external dependencies
        dashboard.add_widgets(
            self._actions_widget(),
            self._box_ai_widget(),
            self._bedrock_widget(),
        )
        dashboard.add_widgets(
            self._caption(
                "**Actions invoked (by action)**",
                "Which agent capabilities are used, and how often. The product's "
                "usage mix at a glance.",
            ),
            self._caption(
                "**Box AI calls & extraction failures**",
                "Box AI call volume (latency/cost driver) vs. parse failures. "
                "Rising failures mean history metadata is silently degrading.",
            ),
            self._caption(
                "**Bedrock invokes / failures / tokens**",
                "Bedrock usage for the research brief. Failures = degraded "
                "narrative; tokens (right axis) track model spend.",
            ),
        )

        # Row 3 — workflow KPIs
        dashboard.add_widgets(
            self._workflow_outcome_widget(),
            self._human_loop_widget(),
            self._risk_mix_widget(),
        )
        dashboard.add_widgets(
            self._caption(
                "**Workflow runs by outcome**",
                "Converged (auto-approved) vs. needs-human vs. hit max "
                "iterations. The core throughput signal.",
            ),
            self._caption(
                "**Human-in-the-loop & avg iterations**",
                "How often a deal needs a human, and how many revise passes it "
                "takes. Rising values = more manual load.",
            ),
            self._caption(
                "**Final risk mix (RED/AMBER/GREEN)**",
                "Risk tier of finalized deals. A RED-heavy mix signals the "
                "pipeline is clearing risky contracts.",
            ),
        )

        CfnOutput(
            self,
            "DashboardURL",
            value=(
                f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
                f"?region={self.region}#dashboards:name={dashboard_name}"
            ),
            description="Direct link to the CloudWatch dashboard.",
        )

    # ------------------------------------------------------------------ #
    # Widget helpers
    # ------------------------------------------------------------------ #
    def _caption(self, title: str, body: str) -> cw.TextWidget:
        """A collapsible caption that sits under a metric widget. Collapsed by
        default (one thin row): the reader sees only the widget name with a
        disclosure triangle, and expands it to read what it tracks and why.
        CloudWatch text widgets render HTML <details>/<summary>, so this keeps
        the dashboard compact while the explanation stays one click away."""
        return cw.TextWidget(
            markdown=(
                f"<details><summary>&#9432; {title}</summary>\n\n{body}\n\n</details>"
            ),
            width=8,
            height=1,
        )

    # ------------------------------------------------------------------ #
    # Metric helpers
    # ------------------------------------------------------------------ #
    def _lambda_metric(self, metric_name: str, dims: dict,
                       stat: str = "Sum") -> cw.Metric:
        return cw.Metric(
            namespace="AWS/Lambda",
            metric_name=metric_name,
            dimensions_map=dims,
            statistic=stat,
            period=Duration.minutes(5),
        )

    def _rc_metric(self, metric_name: str, *, dims: Optional[dict] = None,
                   stat: str = "Sum", label: Optional[str] = None,
                   color: Optional[str] = None) -> cw.Metric:
        return cw.Metric(
            namespace=NAMESPACE,
            metric_name=metric_name,
            dimensions_map=dims or {},
            statistic=stat,
            period=Duration.minutes(5),
            label=label,
            color=color,
        )

    # ------------------------------------------------------------------ #
    # Row 1 — Lambda health
    # ------------------------------------------------------------------ #
    def _lambda_invocations_widget(self, dims: dict) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Lambda invocations & errors",
            width=8,
            height=5,
            left=[
                self._lambda_metric("Invocations", dims),
                self._lambda_metric("Errors", dims),
                self._lambda_metric("Throttles", dims),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _lambda_duration_widget(self, dims: dict) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Lambda duration (p50 / p99) vs 60s timeout",
            width=8,
            height=5,
            left=[
                self._lambda_metric("Duration", dims, stat="p50"),
                self._lambda_metric("Duration", dims, stat="p99"),
            ],
            left_y_axis=cw.YAxisProps(min=0, label="ms"),
            left_annotations=[
                cw.HorizontalAnnotation(
                    value=LAMBDA_TIMEOUT_MS, label="60s timeout", color=RED
                )
            ],
        )

    def _lambda_concurrency_widget(self, dims: dict) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Concurrency",
            width=8,
            height=5,
            left=[self._lambda_metric("ConcurrentExecutions", dims, stat="Maximum")],
            left_y_axis=cw.YAxisProps(min=0),
        )

    # ------------------------------------------------------------------ #
    # Row 2 — external dependencies
    # ------------------------------------------------------------------ #
    def _actions_widget(self) -> cw.GraphWidget:
        actions = [
            "analyze-and-report", "run-workflow", "resume-workflow",
            "grade-deal", "portfolio-radar",
        ]
        return cw.GraphWidget(
            title="Actions invoked (by action)",
            width=8,
            height=5,
            stacked=True,
            left=[
                self._rc_metric("ActionInvoked", dims={"action": a}, label=a)
                for a in actions
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _box_ai_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Box AI calls & extraction failures",
            width=8,
            height=5,
            left=[
                self._rc_metric("BoxAiCall", label="Box AI calls", color=GREEN),
                self._rc_metric("BoxExtractParseFailure",
                                label="extract parse failures", color=RED),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _bedrock_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Bedrock: invokes, failures & tokens",
            width=8,
            height=5,
            left=[
                self._rc_metric("BedrockInvoke", label="invokes", color=BLUE),
                self._rc_metric("BedrockInvokeFailure", label="failures", color=RED),
            ],
            right=[
                self._rc_metric("BedrockInputTokens", label="input tokens", color=BROWN),
                self._rc_metric("BedrockOutputTokens", label="output tokens", color=PINK),
            ],
            left_y_axis=cw.YAxisProps(min=0, label="calls"),
            right_y_axis=cw.YAxisProps(min=0, label="tokens"),
        )

    # ------------------------------------------------------------------ #
    # Row 3 — workflow KPIs
    # ------------------------------------------------------------------ #
    def _workflow_outcome_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Workflow runs by outcome",
            width=8,
            height=5,
            stacked=True,
            left=[
                self._rc_metric("WorkflowRun", dims={"status": "converged"},
                                label="converged", color=GREEN),
                self._rc_metric("WorkflowRun", dims={"status": "needs_human_approval"},
                                label="needs-human", color=AMBER),
                self._rc_metric("WorkflowRun", dims={"status": "max_iterations_reached"},
                                label="max-iterations", color=RED),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _human_loop_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Human-in-the-loop & avg iterations",
            width=8,
            height=5,
            left=[
                self._rc_metric("WorkflowNeedsHuman", label="needs-human", color=AMBER),
            ],
            right=[
                self._rc_metric("WorkflowIterations", stat="Average",
                                label="avg iterations", color=BLUE),
            ],
            left_y_axis=cw.YAxisProps(min=0),
            right_y_axis=cw.YAxisProps(min=0, label="iterations"),
        )

    def _risk_mix_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Final risk mix",
            width=8,
            height=5,
            stacked=True,
            left=[
                self._rc_metric("WorkflowFinalRisk", dims={"risk": "RED"},
                                label="RED", color=RED),
                self._rc_metric("WorkflowFinalRisk", dims={"risk": "AMBER"},
                                label="AMBER", color=AMBER),
                self._rc_metric("WorkflowFinalRisk", dims={"risk": "GREEN"},
                                label="GREEN", color=GREEN),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    # ------------------------------------------------------------------ #
    # Alarms
    # ------------------------------------------------------------------ #
    def _build_alarms(self, lambda_dims: dict,
                      topic: Optional[sns.Topic]) -> None:
        alarms: List[cw.Alarm] = []

        alarms.append(
            cw.Alarm(
                self,
                "LambdaErrorsAlarm",
                alarm_description="Lambda function is returning errors.",
                metric=self._lambda_metric("Errors", lambda_dims),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
        )

        alarms.append(
            cw.Alarm(
                self,
                "LambdaDurationP99Alarm",
                alarm_description="p99 duration approaching the 60s timeout.",
                metric=self._lambda_metric("Duration", lambda_dims, stat="p99"),
                threshold=LAMBDA_TIMEOUT_MS * 0.83,  # ~50s
                evaluation_periods=3,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
        )

        alarms.append(
            cw.Alarm(
                self,
                "BedrockInvokeFailuresAlarm",
                alarm_description="Bedrock model invocations are failing (research brief degraded).",
                metric=self._rc_metric("BedrockInvokeFailure"),
                threshold=3,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
        )

        if topic is not None:
            action = cw_actions.SnsAction(topic)
            for alarm in alarms:
                alarm.add_alarm_action(action)
