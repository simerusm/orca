#!/bin/bash

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Testing deployment API service${NC}"

# Ensure kind cluster is running
echo -e "${YELLOW}Checking Kubernetes cluster status...${NC}"
if ! kubectl get nodes | grep -q "Ready"; then
  echo -e "${RED}Kubernetes cluster is not running. Please start it first.${NC}"
  exit 1
fi
echo -e "${GREEN}Kubernetes cluster is running.${NC}"

# Health check
echo -e "${YELLOW}Testing API health check endpoint...${NC}"
HEALTH_RESPONSE=$(curl -s http://localhost:5002/health)
echo "Health response: $HEALTH_RESPONSE"

# Deploy a sample application
echo -e "${YELLOW}Deploying a sample Node.js application...${NC}"
DEPLOY_RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/bradtraversy/node_crash_course.git",
    "env_vars": {
      "PORT": "5000",
      "NODE_ENV": "production"
    }
  }' \
  http://localhost:5002/deploy)

echo "Deploy response: $DEPLOY_RESPONSE"

# Extract the app name from the response
APP_NAME=$(echo $DEPLOY_RESPONSE | jq -r '.app_name')

if [ -z "$APP_NAME" ]; then
  echo -e "${RED}Failed to get app name from response.${NC}"
  exit 1
fi

echo -e "${GREEN}Deployed application with name: $APP_NAME${NC}"

# List deployments
echo -e "${YELLOW}Listing deployments...${NC}"
curl -s http://localhost:5002/list

echo -e "${YELLOW}Pod status:${NC}"
kubectl get pods -l app=$APP_NAME

# Check service
echo -e "${YELLOW}Service details:${NC}"
kubectl get service $APP_NAME

# Prompt user to delete
echo -e "${YELLOW}Press Enter to delete the deployment or Ctrl+C to keep it running...${NC}"
read

# Delete deployment
echo -e "${YELLOW}Deleting deployment...${NC}"
DELETE_RESPONSE=$(curl -s -X DELETE http://localhost:5002/delete/$APP_NAME)
echo "Delete response: $DELETE_RESPONSE"

echo -e "${GREEN}Test completed!${NC}"