import os
import re
import shutil
import logging
from git import Repo
import subprocess

from api.utils.shell import run_command
from config.templates.node import node_dockerfile
from config.templates.python import python_dockerfile
from config.templates.go import go_dockerfile
from config.templates.static import static_dockerfile

logger = logging.getLogger(__name__)

def detect_project_type(project_dir):
    """Detect the type of project and return appropriate Dockerfile content"""
    # Check for package.json (Node.js)
    if os.path.exists(os.path.join(project_dir, "package.json")):
        return "node", node_dockerfile
    
    # Check for requirements.txt (Python)
    elif os.path.exists(os.path.join(project_dir, "requirements.txt")):
        return "python", python_dockerfile
    
    # Check for go.mod (Go)
    elif os.path.exists(os.path.join(project_dir, "go.mod")):
        return "go", go_dockerfile
    
    # Default to a simple static html site
    else:
        return "static", static_dockerfile

def detect_project_port(project_dir, project_type, env_vars):
    """Auto-detect the port that the application will run on"""
    default_ports = {
        "node": 3000,
        "python": 5000,
        "go": 8080,
        "static": 80
    }
    
    # First check environment variables
    if "PORT" in env_vars:
        try:
            return int(env_vars["PORT"])
        except ValueError:
            logger.warning(f"Invalid PORT in env_vars: {env_vars['PORT']}, using default")
    
    # For Node.js, try to find port in code
    if project_type == "node":
        # Check common files
        for filename in ["index.js", "server.js", "app.js"]:
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    # Look for common port declarations
                    for pattern in [
                        r"\.listen\s*\(\s*(\d+)",  # app.listen(3000)
                        r"port\s*=\s*(\d+)",       # port = 3000
                        r"PORT\s*=\s*(\d+)",       # PORT = 3000
                        r"process\.env\.PORT\s*\|\|\s*(\d+)" # process.env.PORT || 3000
                    ]:
                        matches = re.search(pattern, content)
                        if matches:
                            try:
                                return int(matches.group(1))
                            except ValueError:
                                continue
    
    # For Flask, try to find port in code
    if project_type == "python":
        # Check common files
        for filename in ["app.py", "main.py", "run.py"]:  # Common Flask entry points
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    # Look for common port declarations
                    for pattern in [
                        r"app\.run\s*\(\s*.*port\s*=\s*(\d+)",  # app.run(port=5000)
                        r"port\s*=\s*(\d+)",                    # port = 5000
                        r"PORT\s*=\s*(\d+)",                    # PORT = 5000
                        r"int\(os\.environ\.get\('PORT',\s*'(\d+)'\)",  # int(os.environ.get('PORT', '5000'))
                    ]:
                        matches = re.search(pattern, content)
                        if matches:
                            try:
                                return int(matches.group(1))
                            except ValueError:
                                continue
    
    return default_ports.get(project_type, 80)

def prepare_docker_build(project_dir, env_vars):
    """Prepare project for Docker build"""
    # Check if Dockerfile exists, if not create one based on project type
    dockerfile_path = os.path.join(project_dir, "Dockerfile")
    project_type = "static"  # Default
    
    if not os.path.exists(dockerfile_path):
        logger.info("No Dockerfile found, detecting project type...")
        project_type, dockerfile_content = detect_project_type(project_dir)
        logger.info(f"Detected project type: {project_type}")
        
        # Create the Dockerfile
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        
        logger.info(f"Created {project_type} Dockerfile")
    
    # Create .env file if it doesn't exist
    env_file_path = os.path.join(project_dir, ".env")
    if not os.path.exists(env_file_path) and env_vars:
        with open(env_file_path, "w") as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
        logger.info("Created .env file")
    
    return project_type, dockerfile_path

def build_and_load_image(image_name, project_dir):
    """Build Docker image and load into kind cluster"""
    logger.info(f"Building Docker image: {image_name}")
    
    try:
        run_command(f"docker build -t {image_name} .", cwd=project_dir)
        
        # Load the image into kind
        logger.info(f"Loading image into kind cluster...")
        run_command(f"kind load docker-image {image_name} --name orca")
    except subprocess.CalledProcessError as e:
        logger.error(f"Docker build or load failed: {e.stderr}")
        raise Exception(f"Docker build or load failed: {e.stderr}")

def analyze_repository(repo_url, project_dir):
    """Analyze repository for project type and ports"""
    try:
        Repo.clone_from(repo_url, project_dir)
        project_type, _ = detect_project_type(project_dir)
        
        # Look for port info in common files
        port_info = {}
        for filename in ["index.js", "server.js", "app.js", "app.py", "main.go"]:
            file_path = os.path.join(project_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    port_info[filename] = {}
                    
                    # Look for port declarations
                    for pattern in [
                        r"\.listen\s*\(\s*(\d+)",  # app.listen(3000)
                        r"port\s*=\s*(\d+)",       # port = 3000
                        r"PORT\s*=\s*(\d+)"        # PORT = 3000
                    ]:
                        matches = re.search(pattern, content)
                        if matches:
                            port_info[filename]["detected_port"] = matches.group(1)
        
        return {
            "repo_url": repo_url,
            "project_type": project_type,
            "files": os.listdir(project_dir),
            "port_info": port_info
        }
    finally:
        # Clean up temp directory
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)