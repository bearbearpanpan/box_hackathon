#!/usr/bin/env python3
"""
CDK app entry point for Reality Check observability.

Provisions the observability stack — a CloudWatch dashboard plus baseline alarms
over the agent's telemetry (box/telemetry.py, RealityCheck metric namespace).
Replicable in any account/region; config via CDK context.

Region note: reads the target account/region from CDK_DEFAULT_ACCOUNT /
CDK_DEFAULT_REGION rather than hardcoding.

Context keys (all optional):
  functionName     Lambda the dashboard targets (default reality-check)
  dashboardName    CloudWatch dashboard name    (default RealityCheck)
  alarmEmail       SNS email for alarms         (default: none)
"""
import os

import aws_cdk as cdk

from reality_check_infra.observability_stack import ObservabilityStack

app = cdk.App()

function_name = app.node.try_get_context("functionName") or "reality-check"
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
