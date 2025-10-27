"""
UiPath Job Service

This module provides functionality to start UiPath jobs and poll for their completion
using the UiPath Python SDK.

Required environment variables:
- UIPATH_URL: Your UiPath Orchestrator instance URL
- UIPATH_ACCESS_TOKEN: Authentication token for API access  
- UIPATH_FOLDER_PATH: The full path to your target folder (optional, can use UIPATH_FOLDER_KEY instead)
- UIPATH_FOLDER_KEY: The unique identifier for your target folder (optional, can use UIPATH_FOLDER_PATH instead)

Usage:
    from services.uipath.job_service import UiPathJobService
    
    job_service = UiPathJobService()
    
    # Start a job and wait for completion
    result = job_service.start_job_and_wait(
        process_key="MyProcessKey",
        input_arguments={"param1": "value1", "param2": "value2"},
        timeout_seconds=300
    )
    
    # Or start a job and poll manually
    job_info = job_service.start_job(
        process_key="MyProcessKey",
        input_arguments={"param1": "value1"}
    )
    
    # Poll for completion
    while not job_service.is_job_finished(job_info["Id"]):
        time.sleep(5)
    
    final_result = job_service.get_job_result(job_info["Id"])
"""

import logging
import os
import time
import json
import subprocess
from typing import Dict, Any, Optional, Union, List
from datetime import datetime, timezone
from enum import Enum
from dotenv import load_dotenv, dotenv_values
load_dotenv()

try:
    from uipath import UiPath
except ImportError as e:
    logging.warning(f"UiPath SDK not installed: {e}. Run 'pip install uipath' to use this service.")
    UiPath = None


class JobState(Enum):
    """UiPath job states"""
    PENDING = "Pending"
    RUNNING = "Running" 
    SUCCESSFUL = "Successful"
    FAULTED = "Faulted"
    STOPPED = "Stopped"
    SUSPENDED = "Suspended"
    RESUMED = "Resumed"
    TERMINATING = "Terminating"


class JobPriority(Enum):
    """UiPath job priorities"""
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"


class UiPathJobService:
    """
    Service for managing UiPath job execution.
    
    This class provides methods to start jobs, monitor their progress,
    and retrieve results from UiPath Orchestrator.
    """
    
    def __init__(self, 
                 uipath_url: Optional[str] = None,
                 access_token: Optional[str] = None,
                 folder_path: Optional[str] = None,
                 folder_key: Optional[str] = None,
                 default_timeout: int = 600):
        """
        Initialize the UiPath job service.
        
        Args:
            uipath_url: UiPath Orchestrator URL (defaults to UIPATH_URL env var)
            access_token: Access token for authentication (defaults to UIPATH_ACCESS_TOKEN env var)
            folder_path: Folder path in Orchestrator (defaults to UIPATH_FOLDER_PATH env var)
            folder_key: Folder key in Orchestrator (defaults to UIPATH_FOLDER_KEY env var)
            default_timeout: Default timeout in seconds for job completion (default: 300)
        """
        if UiPath is None:
            raise ImportError("UiPath SDK is not installed. Run 'pip install uipath' to use this service.")
        
        # Get configuration from parameters or environment variables
        self.uipath_url = uipath_url or os.getenv("UIPATH_URL")
        self.access_token = access_token or os.getenv("UIPATH_ACCESS_TOKEN")
        self.folder_path = folder_path or os.getenv("UIPATH_FOLDER_PATH")
        self.folder_key = folder_key or os.getenv("UIPATH_FOLDER_KEY")
        self.default_timeout = default_timeout or os.getenv("UIPATH_DEFAULT_TIMEOUT", 600)
        self.job_id = None
        
        # Validate required configuration
        if not self.uipath_url:
            logging.error(f"UIPATH_URL not found. Current value: {self.uipath_url}")
            raise ValueError("UIPATH_URL must be provided either as parameter or environment variable")
        if not self.access_token:
            logging.error(f"UIPATH_ACCESS_TOKEN not found. Current value: {'***' if self.access_token else None}")
            raise ValueError("UIPATH_ACCESS_TOKEN must be provided either as parameter or environment variable")
        if not (self.folder_path or self.folder_key):
            logging.error(f"No folder configuration found. UIPATH_FOLDER_PATH: {self.folder_path}, UIPATH_FOLDER_KEY: {self.folder_key}")
            raise ValueError("Either UIPATH_FOLDER_PATH or UIPATH_FOLDER_KEY must be provided")
        
        # Initialize UiPath SDK
        try:
            # Set environment variables for UiPath SDK
            if self.folder_path:
                os.environ["UIPATH_FOLDER_PATH"] = self.folder_path
            if self.folder_key:
                os.environ["UIPATH_FOLDER_KEY"] = self.folder_key
            os.environ["UIPATH_URL"] = self.uipath_url
            os.environ["UIPATH_ACCESS_TOKEN"] = self.access_token
            
            self.uipath = UiPath()
            self.processes_service = self.uipath.processes
            self.jobs_service = self.uipath.jobs
            
            logging.info(f"UiPath job service initialized successfully for URL: {self.uipath_url}")
            
            # Validate token on initialization
            if not self.validate_token():
                logging.warning("Token validation failed on initialization, attempting re-authentication...")
                if not self.reauthenticate():
                    raise ValueError("Failed to authenticate with UiPath Orchestrator")
            
        except Exception as e:
            logging.error(f"Failed to initialize UiPath SDK: {str(e)}")
            raise

    def validate_token(self) -> bool:
        """
        Validate if the current access token is still valid.
        
        This method makes a direct HTTP request to the UiPath API to check
        if the token is valid. This is more reliable than trying to retrieve
        a specific job which may return 404 regardless of authentication.
        
        Returns:
            True if token is valid, False if token is invalid (401)
        """
        try:
            import requests
            
            logging.info("Validating UiPath access token...")
            
            # Make a direct API call to a lightweight endpoint that requires auth
            # Using the /odata/Folders endpoint which will return 401 if unauthorized
            # but won't fail with 404 since it's a list endpoint
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            # Extract tenant and organization from URL if needed
            # Format: https://staging.uipath.com/{account}/{tenant}
            url_parts = self.uipath_url.rstrip('/').split('/')
            
            # Build the API URL for folders endpoint
            api_url = f"{self.uipath_url}/odata/Folders"
            
            # Add folder path or key as query parameter if available
            params = {}
            if self.folder_path:
                params['$filter'] = f"FullyQualifiedName eq '{self.folder_path}'"
            
            # Make the request with a short timeout
            response = requests.get(
                api_url,
                headers=headers,
                params=params,
                timeout=10
            )
            
            # Check response status
            if response.status_code == 200:
                logging.info("✅ Token validation successful - authenticated")
                return True
            elif response.status_code == 401:
                logging.warning(f"❌ Token validation failed - 401 Unauthorized")
                return False
            elif response.status_code == 403:
                logging.warning(f"❌ Token validation failed - 403 Forbidden (insufficient permissions)")
                return False
            else:
                # Other status codes - log but assume token might be valid
                # Could be network issues, API problems, etc.
                logging.warning(f"⚠️ Token validation uncertain - HTTP {response.status_code}: {response.text[:200]}")
                # For safety, return False to trigger re-authentication
                return False
                    
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error during token validation: {str(e)}")
            # Network errors don't necessarily mean invalid token
            # But we should re-authenticate to be safe
            return False
        except Exception as e:
            logging.error(f"Error during token validation: {str(e)}")
            return False

    def reauthenticate(self) -> bool:
        """
        Re-authenticate with UiPath using the CLI command.
        
        Uses the following environment variables:
        - UIPATH_CLIENT_ID
        - UIPATH_CLIENT_SECRET
        - UIPATH_URL (default: https://cloud.uipath.com)
        
        Returns:
            True if re-authentication successful, False otherwise
        """
        try:
            logging.info("🔄 Attempting to re-authenticate with UiPath...")
            
            # Get required credentials from environment
            client_id = os.getenv("UIPATH_CLIENT_ID")
            client_secret = os.getenv("UIPATH_CLIENT_SECRET")
            base_url = os.getenv("UIPATH_URL", "https://cloud.uipath.com")
            
            # Validate required credentials
            if not client_id or not client_secret:
                logging.error("❌ Missing UIPATH_CLIENT_ID or UIPATH_CLIENT_SECRET for re-authentication")
                return False
            
            # Build the CLI command, 
            # The uipath cli command using the secret and client id only updates the access token .env in the backend directory
            command = [
                "uipath",
                "auth",
                "--client-id", client_id,
                "--client-secret", client_secret,
                "--base-url", base_url,
                "--scope", "OR.Jobs OR.Execution OR.Folders"
            ]
            
            # Execute the command with environment variables to handle Unicode
            # Set PYTHONIOENCODING to utf-8 to prevent Unicode errors on Windows
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            logging.info(f"Executing: uipath auth --client-id *** --client-secret *** --base-url {base_url}")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
                encoding='utf-8',
                errors='replace'  # Replace Unicode errors with '?' instead of crashing
            )
            
            if result.returncode == 0:
                logging.info("✅ Re-authentication successful")
                logging.debug(f"Output: {result.stdout}")
                
                # The uipath cli command using the secret and client id only updates the access token .env in the backend directory
                # Find backend/.env regardless of current path
                # Check if /app/ exists (Docker) else use backend/
                if os.path.exists('/app/'):
                    ENV_PATH = '/app/.env'
                else:
                    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                    ENV_PATH = os.path.join(BASE_DIR, ".env")

                logging.info(f"Loading environment variables from: {ENV_PATH}")
                env = dotenv_values(ENV_PATH)
                
                # Update the access token 
                new_token = env.get("UIPATH_ACCESS_TOKEN", "N/A")
                if new_token and new_token != self.access_token:
                    self.access_token = new_token
                    os.environ["UIPATH_ACCESS_TOKEN"] = new_token
                    
                    # Reinitialize the UiPath SDK with new token
                    self.uipath = UiPath()
                    self.processes_service = self.uipath.processes
                    self.jobs_service = self.uipath.jobs
                    
                    logging.info("✅ UiPath SDK reinitialized with new token")
                    return True
                else:
                    logging.warning("⚠️ Re-authentication completed but no new token found in environment")
                    return False
            else:
                logging.error(f"❌ Re-authentication failed with return code {result.returncode}")
                logging.error(f"Error: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logging.error("❌ Re-authentication timed out after 30 seconds")
            return False
        except FileNotFoundError:
            logging.error("❌ UiPath CLI not found. Please install UiPath CLI first.")
            return False
        except Exception as e:
            logging.error(f"❌ Error during re-authentication: {str(e)}")
            return False

    def ensure_valid_token(self) -> bool:
        """
        Ensure the token is valid before making API calls.
        Attempts re-authentication if token is invalid.
        
        Returns:
            True if token is valid or successfully re-authenticated, False otherwise
        """
        if not self.validate_token():
            logging.warning("Token invalid, attempting re-authentication...")
            return self.reauthenticate()
        return True

    
    def start_job(self, 
                  process_key: str,
                  input_arguments: Optional[Dict[str, Any]] = None,
                  priority: JobPriority = JobPriority.NORMAL,
                  robot_ids: Optional[List[str]] = None,
                  no_robot: bool = False) -> Dict[str, Any]:
        """
        Start a UiPath job using the processes.invoke() method.
        
        Args:
            process_key: Process key/name to start
            input_arguments: Dictionary of input arguments for the process
            priority: Job priority (default: Normal) - NOTE: Not supported by SDK
            robot_ids: List of specific robot IDs to use (optional) - NOTE: Not supported by SDK
            no_robot: If True, job will run without a robot - NOTE: Not supported by SDK
            
        Returns:
            Job information dictionary containing job key and details
        """
        try:
            # Ensure token is valid before starting job
            if not self.ensure_valid_token():
                raise ValueError("Unable to authenticate with UiPath Orchestrator")
            
            logging.info(f"Starting job for process '{process_key}' with arguments: {input_arguments}")
            
            # Use the processes.invoke() method from the UiPath SDK
            job = self.processes_service.invoke(
                name=process_key,
                input_arguments=input_arguments,
                folder_path=self.folder_path,
                folder_key=self.folder_key
            )
            
            self.job_id = job.id
            
            # The SDK returns a Job object, convert to dictionary for compatibility
            job_info = {
                'Id': str(job.id),
                'Key': str(job.key),
                'State': job.state,
                'ProcessName': process_key,
                'StartTime': job.start_time if isinstance(job.start_time, str) else (job.start_time.isoformat() if job.start_time else None),
                'EndTime': job.end_time if isinstance(job.end_time, str) else (job.end_time.isoformat() if job.end_time else None),
                'InputArguments': json.dumps(input_arguments) if input_arguments else None,
                'OutputArguments': job.output_arguments
            }

            logging.info(f"Job started successfully. job key: {job_info['Key']}, State: {job_info['State']}")
            return job_info
            
        except Exception as e:
            logging.error(f"Failed to start job for process '{process_key}': {str(e)}")
            raise
    
    def get_job_status(self, job_key: str, job_id: int) -> Dict[str, Any]:
        """
        Get the current status of a job using jobs.retrieve().
        
        Args:
            job_key: job key to check
            
        Returns:
            Job status information dictionary
        """
        try:
            # Ensure token is valid before retrieving job status
            if not self.ensure_valid_token():
                raise ValueError("Unable to authenticate with UiPath Orchestrator")
            
            # Use the jobs.retrieve() method from the UiPath SDK
            job = self.jobs_service.retrieve(
                job_key=job_key,
                folder_path=self.folder_path,
                folder_key=self.folder_key
            )
            
            # Convert Job object to dictionary for compatibility
            job_info = {
                'Id': str(job.id),
                'Key': str(job.key),
                'State': job.state,
                'StartTime': job.start_time if isinstance(job.start_time, str) else (job.start_time.isoformat() if job.start_time else None),
                'EndTime': job.end_time if isinstance(job.end_time, str) else (job.end_time.isoformat() if job.end_time else None),
                'InputArguments': job.input_arguments,
                'OutputArguments': job.output_arguments,
                'Info': getattr(job, 'info', None) or getattr(job, 'error_message', None)
            }
            
            logging.debug(f"Retrieved job status for {job_key}: {job_info.get('State', 'Unknown')}")
            return job_info
            
        except Exception as e:
            logging.warning(f"SDK get_job_status failed: {str(e)}, attempting direct API call...")
            return self.get_job_status_direct(job_id)
            
    
    def get_job_status_direct(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Get job status via direct HTTP call, bypassing SDK validation.
        Useful when SDK has Pydantic validation errors.
        
        Args:
            job_key: job key to check (used for logging and fallback)
            job_id: Optional job ID - if provided, skips key-to-id resolution
            
        Returns:
            Job status information dictionary, or None if failed
        """
        try:
            import requests
            
            logging.info(f"Fetching job status directly for {job_id}...")
            
            # Setup headers with authentication and organization unit
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            # Add X-UIPATH-OrganizationUnitId header (required for API calls)
            if self.folder_key:
                headers["X-UIPATH-OrganizationUnitId"] = str(self.folder_key)
                logging.debug(f"Added folder key to headers: {self.folder_key}")
            elif self.folder_path:
                logging.info("Resolving folder ID from folder path...")
                folder_id = self.get_folder_id_from_path(self.folder_path)
                if folder_id:
                    logging.info(f"Resolved folder ID: {folder_id}")
                    headers["X-UIPATH-OrganizationUnitId"] = str(folder_id)
                else:
                    logging.error("Could not resolve folder ID - API call may fail")
            
            job_detail_url = f"{self.uipath_url}/odata/Jobs({job_id})"
            
            logging.debug(f"Fetching job details from: {job_detail_url}")
            response = requests.get(
                job_detail_url,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                job_data = response.json()
                
                # Convert to our standard format
                job_info = {
                    'Id': str(job_data.get('Id', '')),
                    'Key': str(job_data.get('Key', '')),
                    'State': job_data.get('State', ''),
                    'StartTime': job_data.get('StartTime'),
                    'EndTime': job_data.get('EndTime'),
                    'InputArguments': job_data.get('InputArguments'),
                    'OutputArguments': job_data.get('OutputArguments'),
                    'Info': job_data.get('Info', '')
                }
                
                logging.info(f"✅ Retrieved job status directly: {job_info.get('State', 'Unknown')}")
                return job_info
            else:
                logging.error(f"Direct API call failed with status {response.status_code}: {response.text[:200]}")
                return None
                
        except Exception as e:
            logging.error(f"Error in direct job status call: {str(e)}")
            return None
    
    def get_folder_id_from_path(self, folder_path: str) -> Optional[int]:
        """
        Get folder ID from folder path by querying the Folders endpoint.
        
        Args:
            folder_path: Full folder path (e.g., "Agents/Quant")
            
        Returns:
            Folder ID if found, None otherwise
        """
        try:
            import requests
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            api_url = f"{self.uipath_url}/odata/Folders"
            params = {
                "$filter": f"FullyQualifiedName eq '{folder_path}'"
            }
            
            response = requests.get(
                api_url,
                headers=headers,
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('value') and len(data['value']) > 0:
                    folder_id = data['value'][0].get('Id')
                    return folder_id
            
            return None
            
        except Exception as e:
            logging.error(f"Error getting folder ID: {str(e)}")
            return None
    
    def is_job_finished(self, job_key: str) -> bool:
        """
        Check if a job has finished (successfully or with failure).
        
        Args:
            job_key: job key to check
            
        Returns:
            True if job is finished, False if still running
        """
        try:
            job_info = self.get_job_status(job_key, self.job_id)
            state = job_info.get('State', '')
            
            finished_states = [
                JobState.SUCCESSFUL.value,
                JobState.FAULTED.value,
                JobState.STOPPED.value
            ]
            
            return state in finished_states
            
        except Exception as e:
            logging.error(f"Failed to check if job {job_key} is finished: {str(e)}")
            return False
    
    def is_job_successful(self, job_key: str) -> bool:
        """
        Check if a job completed successfully.
        
        Args:
            job_key: job key to check
            
        Returns:
            True if job completed successfully, False otherwise
        """
        try:
            job_info = self.get_job_status(job_key, self.job_id)
            state = job_info.get('State', '')
            
            return state == JobState.SUCCESSFUL.value
            
        except Exception as e:
            logging.error(f"Failed to check if job {job_key} is successful: {str(e)}")
            return False
    
    def wait_for_job_completion(self, 
                              job_key: str, 
                              timeout_seconds: Optional[int] = None,
                              poll_interval: int = 5,
                              max_consecutive_errors: int = 3) -> Dict[str, Any]:
        """
        Wait for a job to complete with polling.
        
        Args:
            job_key: job key to wait for
            timeout_seconds: Maximum time to wait (uses default if None)
            poll_interval: Seconds between status checks (default: 5)
            max_consecutive_errors: Maximum consecutive errors before giving up (default: 3)
            
        Returns:
            Final job status information
            
        Raises:
            TimeoutError: If job doesn't complete within timeout
            RuntimeError: If too many consecutive errors occur
        """
        timeout = timeout_seconds or self.default_timeout
        start_time = time.time()
        consecutive_errors = 0
        last_known_state = None
        
        logging.info(f"Waiting for job {job_key} to complete (timeout: {timeout}s)")
        
        while True:
            try:
                job_info = self.get_job_status(job_key, self.job_id)
                state = job_info.get('State', '')
                last_known_state = state
                
                # Reset error counter on successful status check
                consecutive_errors = 0
                
                # Check if job is finished using the state we just retrieved
                finished_states = [
                    JobState.SUCCESSFUL.value,
                    JobState.FAULTED.value,
                    JobState.STOPPED.value
                ]
                
                if state in finished_states:
                    elapsed_time = time.time() - start_time
                    logging.info(f"Job {job_key} completed with state '{state}' after {elapsed_time:.1f}s")
                    return job_info
                
                # Check timeout
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Job {job_key} did not complete within {timeout} seconds")
                
                logging.debug(f"Job {job_key} state: {state} (elapsed: {time.time() - start_time:.1f}s)")
                time.sleep(poll_interval)
                
            except TimeoutError:
                raise
            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e)
                
                logging.error(f"Error while waiting for job {job_key} (attempt {consecutive_errors}/{max_consecutive_errors}): {error_msg}")
                
                # Check if we've exceeded max consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    error_detail = f"Job {job_key} encountered {consecutive_errors} consecutive errors. Last known state: {last_known_state or 'Unknown'}"
                    logging.error(error_detail)
                    raise RuntimeError(error_detail)
                
                # Check timeout even on errors
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Job {job_key} did not complete within {timeout} seconds (with errors)")
                
                time.sleep(poll_interval)
    
    def get_job_result(self, job_key: str) -> Dict[str, Any]:
        """
        Get the final result of a completed job.
        
        Args:
            job_key: job key to get results for
            
        Returns:
            Dictionary containing job results and output arguments
        """
        try:
            job_info = self.get_job_status(job_key, self.job_id)
            
            result = {
                "job_key": job_key,
                "state": job_info.get('State'),
                "start_time": job_info.get('StartTime'),
                "end_time": job_info.get('EndTime'),
                "output_arguments": {},
                "error_message": None,
                "raw_job_info": job_info
            }
            
            # Parse output arguments if available
            if job_info.get('OutputArguments'):
                try:
                    result["output_arguments"] = json.loads(job_info['OutputArguments'])
                except json.JSONDecodeError:
                    result["output_arguments"] = job_info['OutputArguments']
            else:
                # Print job_info from retrieve
                logging.info(f"job_info from retrieve for job key {job_key}: {json.dumps(job_info, indent=2)}")
                
                # OutputArguments is null - try to extract from attachment
                logging.info(f"OutputArguments is null for job {job_key}, attempting to extract from attachment...")
                try:
                    # Re-Retrieve the full job object from SDK
                    job = self.jobs_service.retrieve(
                        job_key=job_key,
                        folder_path=self.folder_path,
                        folder_key=self.folder_key
                    )
                    
                    # Use extract_output to get output from attachment
                    output_data = self.jobs_service.extract_output(job)
                    
                    if output_data:
                        logging.info(f"✅ Successfully extracted output from attachment for job {job_key}")
                        
                        # extract_output returns a string (JSON), parse it to dictionary
                        if isinstance(output_data, str):
                            try:
                                result["output_arguments"] = json.loads(output_data)
                                #logging.info(f"Parsed output data as JSON: {result['output_arguments']}")
                            except json.JSONDecodeError as json_err:
                                logging.error(f"Failed to parse output data as JSON: {json_err}")
                                raise(json_err)
                        else:
                            # Already a dictionary
                            result["output_arguments"] = output_data
                    else:
                        logging.warning(f"No output data found in attachment for job {job_key}")
                        
                except Exception as extract_error:
                    logging.error(f"Failed to extract output from attachment for job {job_key}: {str(extract_error)}")
                    # Don't raise - continue with empty output_arguments
            
            # Add error information if job failed
            if job_info.get('State') == JobState.FAULTED.value:
                #result["error_message"] = job_info.get('Info', 'Job failed without specific error message')
                raise RuntimeError(job_info.get('Info', 'Job failed without specific error message'))
            
            return result
            
        except Exception as e:
            logging.error(f"Error raised while fetching job result for job key {job_key}: {str(e)}")
            raise
    
    def start_job_and_wait(self, 
                          process_key: str,
                          input_arguments: Optional[Dict[str, Any]] = None,
                          priority: JobPriority = JobPriority.NORMAL,
                          timeout_seconds: Optional[int] = None,
                          poll_interval: int = 5,
                          robot_ids: Optional[List[str]] = None,
                          no_robot: bool = False) -> Dict[str, Any]:
        """
        Start a job and wait for its completion in a single call.
        
        Args:
            process_key: Process key/name to start
            input_arguments: Dictionary of input arguments for the process
            priority: Job priority (default: Normal)
            timeout_seconds: Maximum time to wait for completion
            poll_interval: Seconds between status checks
            robot_ids: List of specific robot IDs to use
            no_robot: If True, job will run without a robot
            
        Returns:
            Dictionary containing complete job result information
        """
        try:
            # Start the job
            job_info = self.start_job(
                process_key=process_key,
                input_arguments=input_arguments,
                priority=priority,
                robot_ids=robot_ids,
                no_robot=no_robot
            )
            
            job_key = job_info.get('Key')
            if not job_key:
                raise ValueError("Could not determine job key from start response")
            
            # Wait for completion
            final_job_info = self.wait_for_job_completion(
                job_key=job_key,
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval
            )
            
            # Get final result
            result = self.get_job_result(job_key)
            
            return result
            
        except Exception as e:
            logging.error(f"Failed to start and wait for job '{process_key}': {str(e)}")
            raise

    
    def test_connection(self) -> bool:
        """
        Test the connection to UiPath Orchestrator.
        
        Since the SDK doesn't provide listing methods, we'll test by
        checking if the UiPath SDK can be initialized properly.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            # Test if we can access the services (basic connectivity check)
            if self.processes_service is None or self.jobs_service is None:
                return False
            
            logging.info("UiPath job service connection test successful")
            return True
            
        except Exception as e:
            logging.error(f"UiPath job service connection test failed: {str(e)}")
            return False


# Example usage and testing
if __name__ == "__main__":
    # Configure logging for detailed output
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        # Initialize the service
        print("🚀 Initializing UiPath job service...")
        job_service = UiPathJobService()
        
        # Test connection first
        print("🔍 Testing connection...")
        if job_service.test_connection():
            print("✅ Connection successful!")
        else:
            print("❌ Connection failed!")
            exit(1)
        
        # Test parameters for trading-investing-agent
        process_name = "trading-investing-agent"
        input_args = {"query": "nvda leaps"}
        folder_path = "Agents/Quant"
        
        print(f"\n🤖 Starting comprehensive job test:")
        print(f"   Process: {process_name}")
        print(f"   Arguments: {input_args}")
        print(f"   Folder: {folder_path}")
        
        """         
        # Test 1: Start job only (manual polling)
        print(f"\n📋 TEST 1: Starting job manually...")
        try:
            job_info = job_service.start_job(
                process_key=process_name,
                input_arguments=input_args
            )
            
            job_key = job_info.get('Key')
            print(f"✅ Job started successfully!")
            print(f"   job key: {job_key}")
            print(f"   Initial State: {job_info.get('State')}")
            print(f"   Start Time: {job_info.get('StartTime')}")
            
            # Poll for completion manually
            print(f"\n⏳ Polling for job completion...")
            start_time = time.time()
            max_wait_time = 300  # 5 minutes
            
            while not job_service.is_job_finished(job_key):
                elapsed = time.time() - start_time
                if elapsed > max_wait_time:
                    print(f"⚠️ Timeout reached ({max_wait_time}s), stopping polling...")
                    break

                current_status = job_service.get_job_status(job_key, job_service.job_id)
                print(f"   Status: {current_status.get('State')} (elapsed: {elapsed:.1f}s)")
                time.sleep(10)  # Check every 10 seconds
            
            # Get final result
            if job_service.is_job_finished(job_key):
                final_result = job_service.get_job_result(job_key)
                print(f"\n✅ Job completed!")
                print(f"   Final State: {final_result.get('state')}")
                print(f"   Duration: {time.time() - start_time:.1f}s")
                
                if job_service.is_job_successful(job_key):
                    print(f"   Success: ✅")
                    if final_result.get('output_arguments'):
                        print(f"   Trade Recommendation: {final_result.get('output_arguments', {})['trade_recommendation']}")
                else:
                    print(f"   Success: ❌")
                    if final_result.get('error_message'):
                        print(f"   Error: {final_result.get('error_message')}")
            
        except Exception as e:
            print(f"❌ Test 1 failed: {str(e)}")
        """       
        # Test 2: Start job and wait (single call)
        print(f"\n📋 TEST 2: Start job and wait in single call...")
        try:
            print(f"🚀 Starting job and waiting for completion...")
            
            result = job_service.start_job_and_wait(
                process_key=process_name,
                input_arguments=input_args,
                timeout_seconds=300,  # 5 minutes
                poll_interval=10      # Check every 10 seconds
            )
            
            print(f"✅ Job completed via start_and_wait!")
            print(f"   job key: {result.get('job_key')}")
            print(f"   Final State: {result.get('state')}")
            print(f"   Start Time: {result.get('start_time')}")
            print(f"   End Time: {result.get('end_time')}")
            
            if result.get('state') == JobState.SUCCESSFUL.value:
                print(f"   Success: ✅")
                if result.get('output_arguments'):
                    print(f"   Trade Recommendation: {result.get('output_arguments', {})['trade_recommendation']}")
            else:
                print(f"   Success: ❌")
                if result.get('error_message'):
                    print(f"   Error: {result.get('error_message')}")
            
        except TimeoutError as e:
            print(f"⚠️ Test 2 timed out: {str(e)}")
        except Exception as e:
            print(f"❌ Test 2 failed: {str(e)}")
        
    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        logging.error(f"UiPath job service test failed: {str(e)}")
        import traceback
        traceback.print_exc()