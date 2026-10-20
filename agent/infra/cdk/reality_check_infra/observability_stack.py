"""
ObservabilityStack — CloudWatch dashboard + baseline alarms for Reality Check.

Visualizes three things operations actually watches:
  1. Lambda service health (invocations, errors, throttles, duration, concurrency)
  2. Review throughput + the Bedrock dependency (reviews run, claims, invokes, token spend)
  3. Review KPIs (results by outcome, risks flagged, claim-severity mix)

Custom metrics live in the "RealityCheck" namespace and are emitted as EMF by
box/telemetry.py when the Lambda runs with EMIT_METRICS=true. AWS/Lambda metrics
are published automatically by the service.

The dashboard is intentionally succinct: three rows of three widgets, each
answering one operational question.

Layout: each row is three graph widgets (height 4) followed by ONE full-width
legend strip (height 1). CloudWatch text widgets render only a Markdown subset
(no raw HTML), so legends are plain Markdown kept to a single dense line.
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
                    f"# Reality Check &mdash; Ops & Utilization\n"
                    f"Lambda **`{function_name}`** &nbsp;·&nbsp; region **`{self.region}`** "
                    f"&nbsp;·&nbsp; metrics **`{NAMESPACE}`** "
                    "(emitted when the Lambda runs with `EMIT_METRICS=true`).\n\n"
                    "**1** Service health &nbsp;·&nbsp; **2** Throughput & Bedrock "
                    "&nbsp;·&nbsp; **3** Review KPIs"
                ),
                width=24,
                height=2,
            )
        )

        # Row 1 — Lambda health
        dashboard.add_widgets(
            self._lambda_invocations_widget(lambda_dims),
            self._lambda_duration_widget(lambda_dims),
            self._lambda_concurrency_widget(lambda_dims),
        )
        dashboard.add_widgets(self._legend(
            ("Invocations / Errors / Throttles",
             "traffic and failure volume; errors or throttles > 0 = work is being dropped"),
            ("Duration p50 / p99 vs 60s",
             "request latency; p99 near the red line = runs about to time out"),
            ("Max concurrency",
             "parallelism in use; nearing the account limit risks throttling"),
        ))

        # Row 2 — review throughput + Bedrock dependency
        dashboard.add_widgets(
            self._actions_widget(),
            self._claims_widget(),
            self._bedrock_widget(),
        )
        dashboard.add_widgets(self._legend(
            ("Contract reviews run",
             "reviews vs. no-match; rising no-match = ingestion drift"),
            ("Claims reviewed",
             "claims checked — the per-run latency & token-spend driver"),
            ("Bedrock invokes / failures / tokens",
             "failures = degraded analysis; tokens (right axis) = model spend"),
        ))

        # Row 3 — review KPIs
        dashboard.add_widgets(
            self._workflow_outcome_widget(),
            self._human_loop_widget(),
            self._risk_mix_widget(),
        )
        dashboard.add_widgets(self._legend(
            ("Claims by result",
             "no-risk / risk-identified / no-source-found"),
            ("Risks flagged",
             "risk-identified count = the human-review workload"),
            ("Claim severity mix",
             "High / Medium / None; High-heavy = materially risky terms"),
        ))

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
    def _legend(self, *items: tuple[str, str]) -> cw.TextWidget:
        """A full-width legend strip that renders below a row of metric widgets.
        CloudWatch text widgets render only a Markdown subset (no raw HTML tags
        like <details>/<summary>), so this keeps the dashboard compact with
        rendering-safe Markdown."""
        cols = [f"**{title}** &mdash; {desc}" for title, desc in items]
        return cw.TextWidget(
            markdown=" &nbsp;·&nbsp; ".join(cols),
            width=24,
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
            height=4,
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
            height=4,
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
            height=4,
            left=[self._lambda_metric("ConcurrentExecutions", dims, stat="Maximum")],
            left_y_axis=cw.YAxisProps(min=0),
        )

    # ------------------------------------------------------------------ #
    # Row 2 — review throughput + Bedrock dependency
    # ------------------------------------------------------------------ #
    def _actions_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Contract reviews run",
            width=8,
            height=4,
            left=[
                self._rc_metric("ReviewRun", label="reviews", color=BLUE),
                self._rc_metric("ReviewNoMatch", label="no-match", color=AMBER),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _claims_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Claims reviewed",
            width=8,
            height=4,
            left=[
                self._rc_metric("ReviewClaims", stat="Sum", label="claims", color=BLUE),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _bedrock_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Bedrock: invokes, failures & tokens",
            width=8,
            height=4,
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
            title="Claims by result",
            width=8,
            height=4,
            stacked=True,
            left=[
                self._rc_metric("ReviewResult", dims={"result": "No risk"},
                                label="no risk", color=GREEN),
                self._rc_metric("ReviewResult", dims={"result": "Risk identified"},
                                label="risk identified", color=RED),
                self._rc_metric("ReviewResult", dims={"result": "No source found"},
                                label="no source found", color=AMBER),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _human_loop_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Risks found vs clean reviews",
            width=8,
            height=4,
            left=[
                self._rc_metric("ReviewResult", dims={"result": "Risk identified"},
                                stat="Sum", label="risks flagged", color=RED),
            ],
            left_y_axis=cw.YAxisProps(min=0),
        )

    def _risk_mix_widget(self) -> cw.GraphWidget:
        return cw.GraphWidget(
            title="Claim severity mix",
            width=8,
            height=4,
            stacked=True,
            left=[
                self._rc_metric("ReviewSeverity", dims={"severity": "High"},
                                label="High", color=RED),
                self._rc_metric("ReviewSeverity", dims={"severity": "Medium"},
                                label="Medium", color=AMBER),
                self._rc_metric("ReviewSeverity", dims={"severity": "None"},
                                label="None", color=GREEN),
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
                alarm_description="Bedrock model invocations are failing (LLM review degraded).",
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
