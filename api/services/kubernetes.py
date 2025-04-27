import os
import yaml
import subprocess
import time
import logging
import socket
import re

from api.utils.shell import run_command
from api.services.build import detect_project_port

logger = logging.getLogger(__name__)

def deploy_to_kubernetes(app_name, image_name, project_type="static", env_vars=None, project_dir=None, workdir=None):
    """Deploy the application to Kubernetes"""
    if env_vars is None:
        env_vars = {}
    
    # Detect port from the project
    container_port = detect_project_port(project_dir, project_type, env_vars)
    logger.info(f"Detected application port: {container_port}")
    
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
    deploy_file = os.path.join(workdir, f"{app_name}-deployment.yaml")
    service_file = os.path.join(workdir, f"{app_name}-service.yaml")
    
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