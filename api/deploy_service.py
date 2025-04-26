#!/usr/bin/env python3

from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import uuid
import yaml
import shutil
import logging
from git import Repo
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use system temp directory for all work
WORKDIR = tempfile.mkdtemp(prefix="k8s-deploy-")

def run_command(command, cwd=None):
    """Run a shell command and return output"""
    logger.info(f"Running: {command}")
    result = subprocess.run(
        command,
        shell=True,
        check=True,
        text=True,
        capture_output=True,
        cwd=cwd
    )
    return result.stdout.strip()

def check_k8s_status():
    """Verify that Kubernetes is running"""
    try:
        nodes = run_command("kubectl get nodes")
        return "Ready" in nodes
    except Exception as e:
        logger.error(f"Kubernetes check failed: {str(e)}")
        return False

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    k8s_status = check_k8s_status()
    return jsonify({
        "status": "healthy" if k8s_status else "unhealthy",
        "kubernetes": "running" if k8s_status else "not running"
    })

@app.route('/deploy', methods=['POST'])
def deploy_app():
    """Deploy application from GitHub repo"""
    data = request.json
    
    if not data or 'repo_url' not in data:
        return jsonify({"error": "Missing required field: repo_url"}), 400
    
    repo_url = data['repo_url']
    env_vars = data.get('env_vars', {})
    
    # Generate a unique ID for this deployment
    deploy_id = str(uuid.uuid4())[:8]
    
    try:
        # 1. Clone the repository
        app_name = f"app-{deploy_id}"
        project_dir = os.path.join(WORKDIR, app_name)
        
        logger.info(f"Cloning {repo_url} to {project_dir}")
        Repo.clone_from(repo_url, project_dir)
        
        # 2. Check if Dockerfile exists, if not create one based on project type
        dockerfile_path = os.path.join(project_dir, "Dockerfile")
        project_type = "static"
        
        if not os.path.exists(dockerfile_path):
            logger.info("No Dockerfile found, detecting project type...")
            project_type, dockerfile_content = detect_project_type(project_dir)
            logger.info(f"Detected project type: {project_type}")
            
            # Create the Dockerfile
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)
            
            logger.info(f"Created {project_type} Dockerfile")
        
        # 3. Create .env file if it doesn't exist
        env_file_path = os.path.join(project_dir, ".env")
        if not os.path.exists(env_file_path) and env_vars:
            with open(env_file_path, "w") as f:
                for key, value in env_vars.items():
                    f.write(f"{key}={value}\n")
            logger.info("Created .env file")
        
        # 4. Build Docker image
        image_name = f"local-deploy/{app_name}:latest"
        logger.info(f"Building Docker image: {image_name}")
        
        # Build the Docker image
        try:
            run_command(f"docker build -t {image_name} .", cwd=project_dir)
            
            # Load the image into kind
            logger.info(f"Loading image into kind cluster...")
            run_command(f"kind load docker-image {image_name} --name orca")
        except subprocess.CalledProcessError as e:
            logger.error(f"Docker build or load failed: {e.stderr}")
            raise Exception(f"Docker build or load failed: {e.stderr}")
        
        # 5. Create Kubernetes deployment
        deploy_to_kubernetes(app_name, image_name, project_type)
        
        # 6. Get service URL
        service_url = get_service_url(app_name)
        
        return jsonify({
            "status": "success",
            "deployment_id": deploy_id,
            "app_name": app_name,
            "service_url": service_url
        })
        
    except Exception as e:
        logger.error(f"Deployment failed: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

def detect_project_type(project_dir):
    """Detect the type of project and return appropriate Dockerfile content"""
    # Check for package.json (Node.js)
    if os.path.exists(os.path.join(project_dir, "package.json")):
        return "node", """FROM node:16-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

# Use environment variables
COPY .env .env
ENV $(cat .env | xargs)

RUN npm run build || echo "No build script found"

EXPOSE 3000

CMD ["npm", "start"]
"""
    
    # Check for requirements.txt (Python)
    elif os.path.exists(os.path.join(project_dir, "requirements.txt")):
        return "python", """FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use environment variables
COPY .env .env
ENV $(cat .env)

EXPOSE 5000

CMD ["python", "app.py"]
"""
    
    # Check for go.mod (Go)
    elif os.path.exists(os.path.join(project_dir, "go.mod")):
        return "go", """FROM golang:1.18-alpine AS build

WORKDIR /app

COPY go.* ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -o /app/server

FROM alpine:3.15
WORKDIR /app
COPY --from=build /app/server .
COPY .env .env

EXPOSE 8080

CMD ["./server"]
"""
    
    # Default to a simple static html site
    else:
        return "static", """FROM nginx:alpine

WORKDIR /usr/share/nginx/html

COPY . .

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
"""

def deploy_to_kubernetes(app_name, image_name, project_type="static"):
    """Deploy the application to Kubernetes"""
    # Determine correct container port based on project type
    container_port = 80  # Default for static sites
    if project_type == "node":
        container_port = 3000
    elif project_type == "python":
        container_port = 5000
    elif project_type == "go":
        container_port = 8080
    
    # Create deployment YAML
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": app_name},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": app_name}},
            "template": {
                "metadata": {"labels": {"app": app_name}},
                "spec": {
                    "containers": [{
                        "name": app_name,
                        "image": image_name,
                        "ports": [{"containerPort": container_port}],
                        "imagePullPolicy": "Never"  # Use local image
                    }]
                }
            }
        }
    }
    
    # Create service YAML
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": app_name},
        "spec": {
            "selector": {"app": app_name},
            "ports": [{"port": 80, "targetPort": container_port}],
            "type": "NodePort"
        }
    }
    
    # Write YAML files
    deploy_file = os.path.join(WORKDIR, f"{app_name}-deployment.yaml")
    service_file = os.path.join(WORKDIR, f"{app_name}-service.yaml")
    
    with open(deploy_file, "w") as f:
        yaml.dump(deployment, f)
    with open(service_file, "w") as f:
        yaml.dump(service, f)
    
    # Apply to Kubernetes
    run_command(f"kubectl apply -f {deploy_file}")
    run_command(f"kubectl apply -f {service_file}")
    
    # Wait for deployment to be ready
    run_command(f"kubectl rollout status deployment/{app_name}")

def get_service_url(app_name):
    """Set up port-forwarding and return localhost URL"""
    try:
        # Find an available port
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        
        # Kill any existing port-forward for this service
        try:
            subprocess.run(f"pkill -f 'kubectl port-forward service/{app_name}'", 
                          shell=True, stderr=subprocess.PIPE)
        except:
            pass
        
        # Get the pod to check if it's ready
        time.sleep(2)  # Give k8s a moment to start the pod
        pod_status = run_command(f"kubectl get pods -l app={app_name} -o jsonpath='{{.items[0].status.phase}}'")
        logger.info(f"Pod status: {pod_status}")
        
        # Start port-forwarding in the background with address binding
        cmd = f"nohup kubectl port-forward service/{app_name} {port}:80 --address 0.0.0.0 > /tmp/port-forward-{app_name}.log 2>&1 &"
        subprocess.Popen(cmd, shell=True)
        
        logger.info(f"Started port-forwarding for {app_name} on port {port}")
        time.sleep(2)  # Give port-forward a moment to establish
        
        # Verify port-forwarding is working
        pf_process = run_command(f"ps aux | grep 'port-forward service/{app_name}' | grep -v grep")
        if not pf_process:
            logger.warning("Port-forwarding process not found, but continuing")
        
        return f"http://localhost:{port}"
    except Exception as e:
        logger.error(f"Error setting up port forwarding: {str(e)}")
        return "Could not set up port forwarding"

@app.route('/delete/<app_name>', methods=['DELETE'])
def delete_deployment(app_name):
    """Delete an existing deployment"""
    try:
        run_command(f"kubectl delete service {app_name}")
        run_command(f"kubectl delete deployment {app_name}")
        
        # We don't need to manually clean files since we're using temp directories
        # that will be auto-cleaned by the OS
        
        return jsonify({
            "status": "success",
            "message": f"Deployment {app_name} deleted"
        })
    except Exception as e:
        logger.error(f"Delete failed: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/list', methods=['GET'])
def list_deployments():
    """List all deployments"""
    try:
        deployments = run_command("kubectl get deployments -o jsonpath='{.items[*].metadata.name}'")
        deployments_list = deployments.split() if deployments else []
        
        details = []
        for app_name in deployments_list:
            if app_name.startswith("app-"):
                service_url = get_service_url(app_name)
                details.append({
                    "app_name": app_name,
                    "service_url": service_url
                })
        
        return jsonify({
            "status": "success",
            "deployments": details
        })
    except Exception as e:
        logger.error(f"List failed: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

if __name__ == '__main__':
    logger.info(f"Using temporary directory: {WORKDIR}")
    logger.info("This directory will be automatically cleaned up when the service exits")
    try:
        app.run(host='0.0.0.0', port=5002, debug=True)
    finally:
        # Clean up temp directory when service exits
        if os.path.exists(WORKDIR):
            logger.info(f"Cleaning up temporary directory: {WORKDIR}")
            shutil.rmtree(WORKDIR)