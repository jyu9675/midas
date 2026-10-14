#!/usr/bin/env bash
# Build the MiDAS image and push it to ECR, ready for App Runner.
# Prereqs (run once in YOUR terminal, not inside Claude):
#   1. AWS CLI installed + an SSO profile configured (`aws configure sso`)
#   2. aws sso login --profile <profile>
#   3. Docker Desktop running
# Then:  AWS_PROFILE=<profile> bash scripts/push_to_ecr.sh
set -euo pipefail

REGION="${REGION:-us-east-1}"
REPO="${REPO:-midas}"
TAG="${TAG:-latest}"

echo ">> identity check"
ACCT=$(aws sts get-caller-identity --query Account --output text)   # fails fast if SSO creds expired
echo "   account=$ACCT region=$REGION repo=$REPO:$TAG"
REGISTRY="$ACCT.dkr.ecr.$REGION.amazonaws.com"

echo ">> ensure ECR repo exists (idempotent)"
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION" \
       --image-scanning-configuration scanOnPush=true >/dev/null

echo ">> docker login to ECR"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo ">> build + tag + push"
docker build -t "$REPO:$TAG" .
docker tag  "$REPO:$TAG" "$REGISTRY/$REPO:$TAG"
docker push "$REGISTRY/$REPO:$TAG"

echo
echo "DONE. Image URI:"
echo "   $REGISTRY/$REPO:$TAG"
echo
echo "Next (App Runner console, one time):"
echo "  Create service -> Container registry -> Amazon ECR -> pick $REPO:$TAG"
echo "  Port 8080, health-check path /api/health"
echo "  Let it auto-create the 'ECR access role' + service-linked role"
echo "  After it's RUNNING: Custom domains -> add midas.nuwaslab.com -> copy the"
echo "  CNAMEs it shows into the nuwaslab.com Route 53 hosted zone (TLS auto-provisions)."
