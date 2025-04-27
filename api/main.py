from flask import Flask
import logging
import tempfile
import os
import shutil

from api.routes.deployment import register_routes

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use system temp directory for all work
WORKDIR = tempfile.mkdtemp(prefix="k8s-deploy-")

def create_app():
    register_routes(app, WORKDIR)
    return app

if __name__ == '__main__':
    logger.info(f"Using temporary directory: {WORKDIR}")
    logger.info("This directory will be automatically cleaned up when the service exits")
    try:
        app = create_app()
        app.run(host='0.0.0.0', port=5002, debug=True)
    finally:
        # Clean up temp directory when service exits
        if os.path.exists(WORKDIR):
            logger.info(f"Cleaning up temporary directory: {WORKDIR}")
            shutil.rmtree(WORKDIR)