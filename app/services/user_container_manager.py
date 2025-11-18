"""User container management for isolated function execution."""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import uuid
import docker
from docker.models.containers import Container
from docker.errors import NotFound, APIError

from app.core.config import settings
from app.models import Function
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class UserContainerManager:
    """Manages long-lived Docker containers per user for function execution."""

    def __init__(self):
        self.client = docker.from_env()
        # Track user containers: {user_id: {"container": Container, "last_used": timestamp}}
        self.user_containers: Dict[str, Dict[str, Any]] = {}
        self.container_lock = asyncio.Lock()
        # Start cleanup task
        self._cleanup_task = None

    async def start_cleanup_task(self):
        """Start background task to cleanup idle containers."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_idle_containers())

    async def _cleanup_idle_containers(self):
        """Background task to stop idle containers."""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes

                idle_timeout = getattr(settings, 'function_container_idle_timeout', 3600)  # 1 hour default
                cutoff_time = time.time() - idle_timeout

                async with self.container_lock:
                    to_remove = []
                    for user_id, info in self.user_containers.items():
                        if info['last_used'] < cutoff_time:
                            try:
                                container = info['container']
                                container.stop(timeout=10)
                                container.remove()
                                to_remove.append(user_id)
                                logger.info(f"Cleaned up idle container for user {user_id}")
                            except Exception as e:
                                logger.error(f"Error cleaning up container for user {user_id}: {e}")

                    for user_id in to_remove:
                        del self.user_containers[user_id]

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def get_or_create_container(
        self,
        user_id: str,
        db: AsyncSession
    ) -> Container:
        """Get existing container for user or create new one."""
        async with self.container_lock:
            # Check if container exists and is running
            if user_id in self.user_containers:
                container_info = self.user_containers[user_id]
                container = container_info['container']

                try:
                    container.reload()
                    if container.status == 'running':
                        # Update last used time
                        container_info['last_used'] = time.time()
                        return container
                    else:
                        # Container stopped, remove and recreate
                        try:
                            container.remove()
                        except:
                            pass
                        del self.user_containers[user_id]
                except NotFound:
                    # Container no longer exists
                    del self.user_containers[user_id]

            # Create new container
            container = await self._create_container(user_id, db)
            self.user_containers[user_id] = {
                'container': container,
                'last_used': time.time()
            }
            return container

    async def _create_container(self, user_id: str, db: AsyncSession) -> Container:
        """Create a new container for user with functions loaded."""
        logger.info(f"Creating new container for user {user_id}")

        # Get container image from settings
        image = getattr(settings, 'function_container_image', 'python:3.11-slim')

        # Create container with resource limits
        container = self.client.containers.run(
            image,
            command='python3 -u /app/executor.py',
            detach=True,
            name=f'sinas-user-{user_id}',
            mem_limit=f"{settings.max_function_memory}m",
            nano_cpus=int(settings.max_function_cpu * 1_000_000_000),  # Convert cores to nanocpus
            storage_opt={'size': settings.max_function_storage},
            network_mode='bridge',
            cap_drop=['ALL'],  # Drop all capabilities for security
            cap_add=['CHOWN', 'SETUID', 'SETGID'],  # Only essential capabilities
            security_opt=['no-new-privileges:true'],  # Prevent privilege escalation
            read_only=False,  # Allow writes to /tmp (needed for Python)
            tmpfs={'/tmp': 'size=100m,mode=1777'},  # Temp storage
            environment={
                'PYTHONUNBUFFERED': '1',
                'USER_ID': user_id,
            },
            labels={
                'sinas.user_id': user_id,
                'sinas.type': 'function-executor',
            },
            stdin_open=True,
            tty=False,
        )

        # Wait for container to be ready
        await asyncio.sleep(1)

        # Load user's functions into container
        await self._sync_functions(container, user_id, db)

        logger.info(f"Container created for user {user_id}: {container.id[:12]}")
        return container

    async def _sync_functions(self, container: Container, user_id: str, db: AsyncSession):
        """Load all functions user has access to into container namespace."""
        from app.models.user import GroupMember

        # Get user's groups
        groups_result = await db.execute(
            select(GroupMember.group_id).where(GroupMember.user_id == user_id)
        )
        group_ids = [row[0] for row in groups_result.all()]

        # Load functions from user's groups + user's own functions
        result = await db.execute(
            select(Function).where(
                Function.is_active == True,
                (Function.user_id == user_id) | (Function.group_id.in_(group_ids))
            )
        )
        functions = result.scalars().all()

        # Build functions payload
        functions_data = {}
        for func in functions:
            functions_data[func.name] = {
                'code': func.code,
                'input_schema': func.input_schema,
                'output_schema': func.output_schema,
            }

        # Send functions to container via stdin
        payload = {
            'action': 'load_functions',
            'functions': functions_data,
        }

        # Write to container (executor.py will read this)
        try:
            exec_result = container.exec_run(
                cmd=['python3', '-c', f'''
import sys
import json
payload = {json.dumps(payload)}
# Write to a file that executor.py will read
with open("/tmp/functions.json", "w") as f:
    json.dump(payload, f)
'''],
                detach=False,
            )
            logger.info(f"Loaded {len(functions)} functions into container for user {user_id}")
        except Exception as e:
            logger.error(f"Error syncing functions to container: {e}")

    async def execute_function(
        self,
        user_id: str,
        function_name: str,
        input_data: Dict[str, Any],
        execution_id: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute a function in user's container."""
        container = await self.get_or_create_container(user_id, db)

        # Update last used time
        async with self.container_lock:
            if user_id in self.user_containers:
                self.user_containers[user_id]['last_used'] = time.time()

        # Prepare execution payload
        payload = {
            'action': 'execute',
            'execution_id': execution_id,
            'function_name': function_name,
            'input_data': input_data,
        }

        try:
            # Execute via exec_run
            exec_result = container.exec_run(
                cmd=['python3', '-c', f'''
import sys
import json
payload = {json.dumps(payload)}
# Write execution request
with open("/tmp/exec_request.json", "w") as f:
    json.dump(payload, f)
# Trigger execution
with open("/tmp/exec_trigger", "w") as f:
    f.write("1")
# Wait for result
import time
max_wait = {settings.function_timeout}
start = time.time()
while time.time() - start < max_wait:
    try:
        with open("/tmp/exec_result.json", "r") as f:
            result = json.load(f)
            # Clear files
            import os
            os.remove("/tmp/exec_result.json")
            os.remove("/tmp/exec_trigger")
            print(json.dumps(result))
            sys.exit(0)
    except FileNotFoundError:
        time.sleep(0.1)
        continue
print(json.dumps({{"error": "Execution timeout"}}))
sys.exit(1)
'''],
                demux=True,
            )

            stdout, stderr = exec_result.output

            if exec_result.exit_code != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise Exception(f"Execution failed: {error_msg}")

            result = json.loads(stdout.decode())

            if 'error' in result:
                raise Exception(result['error'])

            return result

        except Exception as e:
            logger.error(f"Error executing function in container: {e}")
            raise

    async def reload_functions(self, user_id: str, db: AsyncSession):
        """Reload functions in user's container after function changes."""
        async with self.container_lock:
            if user_id in self.user_containers:
                container = self.user_containers[user_id]['container']
                try:
                    await self._sync_functions(container, user_id, db)
                except Exception as e:
                    logger.error(f"Error reloading functions: {e}")

    async def stop_container(self, user_id: str):
        """Stop and remove container for user."""
        async with self.container_lock:
            if user_id in self.user_containers:
                try:
                    container = self.user_containers[user_id]['container']
                    container.stop(timeout=10)
                    container.remove()
                    logger.info(f"Stopped container for user {user_id}")
                except Exception as e:
                    logger.error(f"Error stopping container: {e}")
                finally:
                    del self.user_containers[user_id]

    async def get_container_stats(self) -> List[Dict[str, Any]]:
        """Get stats for all managed containers."""
        stats = []
        async with self.container_lock:
            for user_id, info in self.user_containers.items():
                try:
                    container = info['container']
                    container.reload()
                    stats.append({
                        'user_id': user_id,
                        'container_id': container.id[:12],
                        'status': container.status,
                        'last_used': datetime.fromtimestamp(info['last_used']).isoformat(),
                        'idle_seconds': int(time.time() - info['last_used']),
                    })
                except Exception as e:
                    logger.error(f"Error getting stats for container: {e}")
        return stats


# Global instance
container_manager = UserContainerManager()
