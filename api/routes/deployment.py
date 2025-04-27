from flask import request, jsonify
import os
import uuid
import tempfile
from git import Repo
import re
import logging

from api.services.kubernetes import deploy_to_kubernetes, get_service_url
from api.services.build import detect_project_type, detect_project_port

logger = logging.getLogger(__name__)

def register_routes(app, WORKDIR):
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        from api.utils.shell import run_command
        try:
            nodes = run_command("kubectl get nodes")
            k8s_status = "Ready" in nodes
        except Exception:
            k8s_status = False
            
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
            from api.services.build import prepare_docker_build
            project_type, dockerfile_path = prepare_docker_build(project_dir, env_vars)
            
            # 3. Build Docker image
            from api.services.build import build_and_load_image
            image_name = f"local-deploy/{app_name}:latest"
            build_and_load_image(image_name, project_dir)
            
            # 4. Create Kubernetes deployment
            deploy_to_kubernetes(app_name, image_name, project_type, env_vars, project_dir, WORKDIR)
            
            # 5. Get service URL
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

    @app.route('/delete/<app_name>', methods=['DELETE'])
    def delete_deployment(app_name):
        """Delete an existing deployment"""
        from api.utils.shell import run_command
        try:
            run_command(f"kubectl delete service {app_name}")
            run_command(f"kubectl delete deployment {app_name}")
            
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
        from api.utils.shell import run_command
        try:
            deployments = run_command("kubectl get deployments -o jsonpath='{.items[*].metadata.name}'")
            deployments_list = deployments.split() if deployments else []
            
            details = []
            for app_name in deployments_list:
                if app_name.startswith("app-"):
                    # Check if there's an existing port-forward
                    try:
                        pf_process = run_command(f"ps aux | grep 'port-forward service/{app_name}' | grep -v grep")
                        if pf_process:
                            # Extract port from existing process
                            port = re.search(r'(\d+):80', pf_process).group(1)
                            service_url = f"http://localhost:{port}"
                        else:
                            service_url = get_service_url(app_name)
                    except:
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

    @app.route('/analyze', methods=['POST'])
    def analyze_repo():
        """Analyze a repo without deploying"""
        data = request.json
        repo_url = data['repo_url']
        deploy_id = str(uuid.uuid4())[:8]
        project_dir = os.path.join(WORKDIR, f"analyze-{deploy_id}")
        
        try:
            from api.services.build import analyze_repository
            analysis = analyze_repository(repo_url, project_dir)
            return jsonify(analysis)
        except Exception as e:
            logger.error(f"Analysis failed: {str(e)}")
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500