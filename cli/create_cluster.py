import subprocess
import tempfile
import time
import os
import sys
import yaml

def run_command(command, check=True):
    """Run a shell command and return the output"""
    try:
        result = subprocess.run(
            command,
            check=check,
            text=True,
            capture_output=True,
            shell=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {command}")
        print(f"Error output: {e.stderr}")
        if check:
            sys.exit(1)
        return e.stderr

def check_prerequisites():
    """Verify that required tools are installed"""
    prerequisites = ["docker", "kind", "kubectl"]
    
    for tool in prerequisites:
        try:
            version = run_command(f"{tool} version", check=False)
            print(f"✅ {tool} is installed: {version.splitlines()[0]}")
        except FileNotFoundError:
            print(f"❌ {tool} is not installed. Please install it before proceeding.")
            sys.exit(1)

def create_cluster_config():
    """Create a multi-node cluster configuration YAML"""
    cluster_config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [
            {
                "role": "control-plane"
            },
            {
                "role": "worker"
            },
            {
                "role": "worker"
            }
        ]
    }
    
    # Create a temporary file for the configuration
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp:
        yaml.dump(cluster_config, temp, default_flow_style=False)
        return temp.name

def create_cluster(config_path):
    """Create a kind cluster using the provided configuration"""
    cluster_name = "orca"
    
    # Check if the cluster already exists
    existing_clusters = run_command("kind get clusters")
    if cluster_name in existing_clusters.split():
        print(f"Cluster '{cluster_name}' already exists. Deleting it first...")
        run_command(f"kind delete cluster --name {cluster_name}")
    
    # Create the cluster
    print(f"Creating kind cluster '{cluster_name}' with 1 control-plane and 2 workers...")
    result = run_command(f"kind create cluster --config={config_path} --name {cluster_name}")
    print(result)

def wait_for_nodes_ready():
    """Wait for all nodes to be in Ready state"""
    print("Waiting for nodes to be ready...")
    
    max_attempts = 30
    for attempt in range(max_attempts):
        nodes_output = run_command("kubectl get nodes -o wide")
        if nodes_output and "NotReady" not in nodes_output:
            print("All nodes are ready!")
            print("\nCluster node status:")
            print(nodes_output)
            return True
        
        print(f"Nodes not ready yet (attempt {attempt+1}/{max_attempts}). Waiting 10 seconds...")
        time.sleep(10)
    
    print("Timed out waiting for nodes to be ready.")
    return False

def main():
    print("Starting multi-node Kubernetes cluster setup with kind...")
    
    # Check prerequisites
    check_prerequisites()
    
    # Create cluster configuration
    config_path = create_cluster_config()
    print(f"Created cluster configuration at: {config_path}")
    
    try:
        # Create the cluster
        create_cluster(config_path)
        
        # Wait for nodes to be ready
        if wait_for_nodes_ready():
            print("\n🎉 Cluster 'orca' created successfully with 1 control-plane and 2 worker nodes!")
            print("You can now use 'kubectl' to interact with your cluster.")
    finally:
        # Clean up the temporary configuration file
        os.unlink(config_path)

if __name__ == "__main__":
    main()