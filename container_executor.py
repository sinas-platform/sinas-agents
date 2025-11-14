"""
Executor script that runs inside user containers.
This script loads functions and executes them on demand.
"""
import json
import sys
import time
import traceback
from typing import Dict, Any


class ContainerExecutor:
    def __init__(self):
        self.namespace = {
            '__builtins__': __builtins__,
            'json': json,
        }
        # Import common modules
        try:
            import datetime
            import uuid
            self.namespace['datetime'] = datetime
            self.namespace['uuid'] = uuid
        except ImportError:
            pass

    def load_functions(self, functions_data: Dict[str, Dict[str, Any]]):
        """Load functions into namespace."""
        for name, func_data in functions_data.items():
            try:
                code = func_data['code']
                # Compile and execute function in namespace
                compiled_code = compile(code, f'<function:{name}>', 'exec')
                exec(compiled_code, self.namespace)
                print(f"Loaded function: {name}", file=sys.stderr)
            except Exception as e:
                print(f"Error loading function {name}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

    def execute_function(
        self,
        function_name: str,
        input_data: Dict[str, Any],
        execution_id: str
    ) -> Dict[str, Any]:
        """Execute a function from the namespace."""
        try:
            if function_name not in self.namespace:
                return {
                    'error': f"Function '{function_name}' not found in namespace",
                    'execution_id': execution_id,
                }

            func = self.namespace[function_name]

            # Execute function
            start_time = time.time()
            result = func(input_data)
            duration_ms = int((time.time() - start_time) * 1000)

            return {
                'result': result,
                'execution_id': execution_id,
                'duration_ms': duration_ms,
                'status': 'completed',
            }

        except Exception as e:
            return {
                'error': str(e),
                'traceback': traceback.format_exc(),
                'execution_id': execution_id,
                'status': 'failed',
            }

    def run(self):
        """Main loop - wait for execution requests."""
        print("Container executor started", file=sys.stderr)

        # Load initial functions if available
        try:
            with open('/tmp/functions.json', 'r') as f:
                payload = json.load(f)
                if payload.get('action') == 'load_functions':
                    self.load_functions(payload['functions'])
        except FileNotFoundError:
            print("No initial functions to load", file=sys.stderr)
        except Exception as e:
            print(f"Error loading initial functions: {e}", file=sys.stderr)

        # Main execution loop
        while True:
            try:
                # Check for execution trigger
                try:
                    with open('/tmp/exec_trigger', 'r') as f:
                        f.read()

                    # Read execution request
                    with open('/tmp/exec_request.json', 'r') as f:
                        request = json.load(f)

                    action = request.get('action')

                    if action == 'execute':
                        # Execute function
                        result = self.execute_function(
                            request['function_name'],
                            request['input_data'],
                            request['execution_id']
                        )

                        # Write result
                        with open('/tmp/exec_result.json', 'w') as f:
                            json.dump(result, f)

                    elif action == 'load_functions':
                        # Reload functions
                        self.load_functions(request['functions'])
                        with open('/tmp/exec_result.json', 'w') as f:
                            json.dump({'status': 'loaded'}, f)

                    # Clear request file
                    import os
                    try:
                        os.remove('/tmp/exec_request.json')
                    except:
                        pass

                except FileNotFoundError:
                    # No execution pending, wait
                    time.sleep(0.1)
                    continue

            except KeyboardInterrupt:
                print("Executor shutting down", file=sys.stderr)
                break
            except Exception as e:
                print(f"Error in executor loop: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                time.sleep(0.1)


if __name__ == '__main__':
    executor = ContainerExecutor()
    executor.run()
