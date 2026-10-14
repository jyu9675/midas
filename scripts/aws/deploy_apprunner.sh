#!/usr/bin/env bash
# Create or update the MiDAS App Runner service from the ECR image.
# Run push_to_ecr.sh first (builds + pushes the image), then this.
# Prereqs: aws sso login --profile <profile>; admin (or App Runner + ECR + IAM) perms.
#
# Usage:  AWS_PROFILE=<profile> bash scripts/aws/deploy_apprunner.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
SERVICE="${SERVICE:-midas}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The ECR access role App Runner assumes to pull the private image (idempotent).
ACCT=$(aws sts get-caller-identity --query Account --output text)
if ! aws iam get-role --role-name AppRunnerECRAccessRole >/dev/null 2>&1; then
  aws iam create-role --role-name AppRunnerECRAccessRole \
    --assume-role-policy-document "file://$HERE/ecr-access-trust.json" >/dev/null
  aws iam attach-role-policy --role-name AppRunnerECRAccessRole \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
fi

ARN=$(aws apprunner list-services --region "$REGION" \
        --query "ServiceSummaryList[?ServiceName=='$SERVICE'].ServiceArn | [0]" --output text)

if [ "$ARN" = "None" ] || [ -z "$ARN" ]; then
  echo ">> creating service $SERVICE"
  # IMPORTANT: ImageConfiguration.StartCommand is required — App Runner does not
  # reliably honor the image's default CMD (container exits instantly, no logs).
  aws apprunner create-service --region "$REGION" --service-name "$SERVICE" \
    --source-configuration "file://$HERE/apprunner-source.json" \
    --instance-configuration "file://$HERE/apprunner-instance.json" \
    --query "Service.{arn:ServiceArn,url:ServiceUrl,status:Status}" --output json
elif [ "${MODE:-image}" = "config" ]; then
  echo ">> updating service CONFIG for $SERVICE ($ARN)"
  # update-service applies config (StartCommand, instance role, cpu/mem) but does
  # NOT re-pull :latest. Use MODE=config only when the service config changed.
  aws apprunner update-service --region "$REGION" --service-arn "$ARN" \
    --source-configuration "file://$HERE/apprunner-source.json" \
    --instance-configuration "file://$HERE/apprunner-instance.json" \
    --query "Service.{arn:ServiceArn,url:ServiceUrl,status:Status}" --output json
  echo ">> NOTE: config updated. To also deploy the new image, re-run without MODE=config."
else
  echo ">> deploying freshly-pushed :latest image to $SERVICE ($ARN)"
  # AutoDeployments are off, so pull + deploy the new image explicitly.
  # (This is the normal redeploy after scripts/push_to_ecr.sh.)
  aws apprunner start-deployment --service-arn "$ARN" --region "$REGION" --query "OperationId" --output text
fi
