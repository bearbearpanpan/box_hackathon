#!/usr/bin/env python3
"""
CDK app entry point for Reality Check infrastructure.

Today this provisions the observability stack (CloudWatch dashboard + baseline
alarms) that visualizes the telemetry emitted by box/telemetry.py. The Lambda
and Bedrock agent are still deployed per agent/infra/setup.md; as that moves to
CDK it can be added here as additional stacks on the same App.

Region note: this account uses the "new AWS experience" where all regional
resources must live in the project's single assigned Region. We read the target
account/region from the standard CDK environment (CDK_DEFAULT_ACCOUNT/REGION or
--context) rather than hardcoding, so it deploys into whatever Region the
project is pinned to.
"""
import os

import aws_cdk as cdk

from reality_check_infra.observability_stack import ObservabilityStack

app = cdk.App()

# Config via context (cdk deploy -c key=value) with sensible defaults.
function_name = app.node.try_get_context("functionName") or "reality-check-tools"
dashboard_name = app.node.try_get_context("dashboardName") or "RealityCheck"
alarm_email = app.node.try_get_context("alarmEmail")  # optional

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

ObservabilityStack(
    app,
    "RealityCheckObservability",
    function_name=function_name,
    dashboard_name=dashboard_name,
    alarm_email=alarm_email,
    env=env,
    description="Reality Check observability: CloudWatch dashboard + baseline alarms.",
)

app.synth()
