import asyncio
import os
import uuid
import logging

logger = logging.getLogger("ASTRA_CORE.executor")

async def execute_python_code(code: str, workspace_dir: str = "workspace", timeout: int = 60) -> dict:
    """
    Saves the Python code in the workspace and executes it asynchronously in an isolated subprocess.
    Captures standard output, error, and respects a timeout to prevent infinite loops in solvers.
    """
    os.makedirs(workspace_dir, exist_ok=True)
    
    # Generate a unique filename to avoid async collisions
    filename = f"astra_exec_{uuid.uuid4().hex[:8]}.py"
    filepath = os.path.join(workspace_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)
        
    logger.info(f"Oracle validating script: {filepath}")
    
    try:
        # Start the subprocess without blocking the main event loop
        process = await asyncio.create_subprocess_exec(
            "python", filepath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            # Wait for execution with a time limit
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()  # Clear buffers
            logger.warning(f"Timeout of {timeout}s exceeded in {filepath}")
            return {
                "stdout": "",
                "stderr": f"TimeoutError: The Python solver exceeded the limit of {timeout} seconds (possible infinite loop or intractable computation).",
                "exit_code": 124
            }
            
        return {
            "stdout": stdout.decode('utf-8', errors='replace'),
            "stderr": stderr.decode('utf-8', errors='replace'),
            "exit_code": process.returncode
        }
        
    except Exception as e:
        logger.error(f"Structural failure invoking the subprocess: {e}")
        return {
            "stdout": "",
            "stderr": f"SystemError: Failed to launch python in {filepath} -> {str(e)}",
            "exit_code": -1
        }
