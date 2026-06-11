import json
import logging
import os

import requests

log = logging.getLogger(__name__)

# --- API Endpoints ---
API_BASE_URL = "https://multiup.io/api"
LOGIN_URL = f"{API_BASE_URL}/login"
GET_SERVER_URL = f"{API_BASE_URL}/get-fastest-server"
GET_HOSTS_URL = f"{API_BASE_URL}/get-list-hosts"
# Upload URL is dynamic, obtained from GET_SERVER_URL


def login(username, password):
    """Logs into MultiUp.io account."""
    log.debug("Attempting login...")
    try:
        payload = {"username": username, "password": password}
        response = requests.post(LOGIN_URL, data=payload)
        response.raise_for_status()  # Raise an exception for bad status codes
        data = response.json()

        # Check if the 'error' field indicates success ('ok' or 'success')
        error_status = data.get("error")
        if error_status not in ("ok", "success"):
            log.error(f"Login failed: {error_status}")
            return None

        log.debug(f"Login successful for user: {data.get('login')}")
        return data.get("user")  # Return user ID
    except requests.exceptions.RequestException as e:
        log.error(f"Login request failed: {e}")
        return None
    except json.JSONDecodeError:
        log.error("Failed to parse login response.")
        log.debug(f"Raw response: {response.text}")
        return None


def get_fastest_server(file_size):
    """Gets the fastest server URL for uploading."""
    log.debug("Getting fastest upload server...")
    try:
        params = {"size": file_size}
        response = requests.get(GET_SERVER_URL, params=params)
        response.raise_for_status()
        data = response.json()

        # Check if the 'error' field indicates success ('ok' or 'success')
        error_status = data.get("error")
        if error_status not in ("ok", "success"):
            log.error(f"Failed to get server: {error_status}")
            return None

        server_url = data.get("server")
        log.debug(f"Fastest server found: {server_url}")
        return server_url
    except requests.exceptions.RequestException as e:
        log.error(f"Get server request failed: {e}")
        return None
    except json.JSONDecodeError:
        log.error("Failed to parse get server response.")
        log.debug(f"Raw response: {response.text}")
        return None


def get_available_hosts():
    """Gets the list of available hosts."""
    log.debug("Getting available hosts...")
    try:
        response = requests.get(GET_HOSTS_URL)
        response.raise_for_status()
        data = response.json()

        # Check if the 'error' field indicates success ('ok' or 'success')
        error_status = data.get("error")
        if error_status not in ("ok", "success"):
            log.error(f"Failed to get hosts: {error_status}")
            return None

        # Return the full hosts dictionary for more detailed host info
        log.debug(f"Found {len(data.get('hosts', {}))} available hosts.")
        return data.get("hosts", {})
    except requests.exceptions.RequestException as e:
        log.error(f"Get hosts request failed: {e}")
        return None
    except json.JSONDecodeError:
        log.error("Failed to parse get hosts response.")
        log.debug(f"Raw response: {response.text}")
        return None


def select_priority_hosts(hosts_dict, file_size, max_hosts=10, priority_list=None):
    """Selects hosts with priority for specified hosts, up to max_hosts."""
    if priority_list is None:
        # Map user-friendly names to API host names
        # The first element in each tuple is the user-friendly name, the second is the API host name
        host_name_mapping = [
            ("1Fichier", "1fichier.com"),
            ("BuzzHeavier", "buzzheavier.com"),
            ("Clicknupload", "clicknupload.click"),
            ("Daily Uploads", "dailyuploads.net"),
            ("FastUpload", "fastupload.io"),
            ("GoFile", "gofile.io"),
            ("Google Drive", "drive.google.com"),
            ("HexUpload", "hexload.com"),
            ("Krakenfiles", "krakenfiles.com"),
            ("MediaFire", "mediafire.com"),
            ("MEGA", "mega.nz"),
            ("Mixdrop", "mixdrop.ag"),
            ("Sendcm", "media.cm"),
        ]

        # Extract just the API host names for our priority list
        priority_list = [api_name for _, api_name in host_name_mapping]

    # Check which priority hosts actually exist in the API response
    available_hosts = set(hosts_dict.keys())
    missing_hosts = [host for host in priority_list if host not in available_hosts]
    if missing_hosts:
        log.debug("The following hosts from your priority list are not available:")
        for host in missing_hosts:
            log.debug(f"  - {host}")

        # Filter out non-existent hosts
        priority_list = [host for host in priority_list if host in available_hosts]
        log.debug(f"Continuing with {len(priority_list)} valid priority hosts.")

    selected_hosts = []
    remaining_hosts = []

    # Print info about file size
    file_size_mb = file_size / (1024 * 1024)
    log.debug(f"File size: {file_size_mb:.2f} MB")

    # First, check which hosts from the priority list are available
    for host_name, host_info in hosts_dict.items():
        # The API returns size in MB, convert to bytes for comparison
        # If size is missing, assume 0 (unlimited)
        host_max_size_mb = int(host_info.get("size", 0))
        host_max_size = host_max_size_mb * 1024 * 1024  # Convert MB to bytes

        # Check if host can handle file size
        if host_max_size >= file_size or host_max_size == 0:  # 0 might mean unlimited
            # Add to selected hosts if it's in priority list
            if host_name in priority_list:
                selected_hosts.append((host_name, host_max_size))
            else:
                remaining_hosts.append((host_name, host_max_size))

    # If no hosts in priority list can handle the file size, show which ones might be available
    if not selected_hosts:
        log.debug(
            "Your file is too large for the priority hosts. "
            "Here are hosts that can handle your file size:"
        )
        suitable_hosts = []

        for host_name, host_info in hosts_dict.items():
            host_max_size_mb = int(host_info.get("size", 0))
            host_max_size = host_max_size_mb * 1024 * 1024  # Convert MB to bytes

            if host_max_size >= file_size or host_max_size == 0:
                max_size_mb = host_max_size_mb if host_max_size_mb > 0 else "Unlimited"
                if isinstance(max_size_mb, int):
                    suitable_hosts.append((host_name, f"{max_size_mb} MB"))
                else:
                    suitable_hosts.append((host_name, max_size_mb))

        if suitable_hosts:
            for host, size in suitable_hosts:
                log.debug(f"  - {host} (Max size: {size})")

            # Ask if user wants to use these hosts instead
            log.debug("Would you like to use these hosts instead? (y/n)")
            user_choice = input().strip().lower()

            if user_choice == "y" or user_choice == "yes":
                # Reset and add all suitable hosts
                selected_hosts = []
                remaining_hosts = []

                for host_name, host_info in hosts_dict.items():
                    host_max_size_mb = int(host_info.get("size", 0))
                    host_max_size = host_max_size_mb * 1024 * 1024

                    if host_max_size >= file_size or host_max_size == 0:
                        remaining_hosts.append((host_name, host_max_size))
        else:
            print("No hosts can handle a file of this size.")

    # Sort priority hosts by name to maintain order similar to priority list
    selected_hosts.sort(key=lambda x: priority_list.index(x[0]) if x[0] in priority_list else 999)

    # If we have less than max_hosts from priority list
    # add others based on max file size (largest first)
    if len(selected_hosts) < max_hosts:
        # Sort remaining hosts by max file size (descending)
        remaining_hosts.sort(key=lambda x: x[1], reverse=True)
        remaining_needed = max_hosts - len(selected_hosts)
        selected_hosts.extend(remaining_hosts[:remaining_needed])
    else:
        # If we have more than max_hosts from priority list, keep only top ones
        selected_hosts = selected_hosts[:max_hosts]

    if selected_hosts:
        log.debug(f"Selected {len(selected_hosts)} hosts for upload:")
        for host, size in selected_hosts:
            if size > 0:
                # size is already in bytes, convert back to MB for display
                max_size_mb = size / (1024 * 1024)
                log.debug(f"  - {host} (Max size: {int(max_size_mb)} MB)")
            else:
                log.debug(f"  - {host} (Max size: Unlimited)")
    else:
        log.debug("No hosts selected for upload.")

    # Return just the host names
    return [host[0] for host in selected_hosts]


def upload_file(file_path, user_id=None, hosts_dict=None, max_hosts=10):
    """Uploads the file to the specified server."""
    if not os.path.exists(file_path):
        log.error(f"File not found at {file_path}")
        return None

    if hosts_dict is None:
        hosts_dict = get_available_hosts()
        if not hosts_dict:
            log.error("Could not retrieve available hosts.")
            return None

    file_size = os.path.getsize(file_path)

    # Get the fastest server URL for uploading
    upload_url = get_fastest_server(file_size)

    # Select hosts, prioritizing the specified list
    selected_hosts = select_priority_hosts(hosts_dict, file_size, max_hosts)
    if not selected_hosts:
        log.error("No suitable hosts selected for file size.")
        log.error("Please try a smaller file or use different host priorities.")
        return None

    log.debug(f"Preparing to upload '{os.path.basename(file_path)}' to {upload_url}...")

    try:
        with open(file_path, "rb") as f:
            files = {"files[]": (os.path.basename(file_path), f)}
            payload = {}
            if user_id:
                payload["user"] = user_id
                log.debug(f"Uploading as user ID: {user_id}")

            # Add selected hosts to the payload
            for host in selected_hosts:
                payload[host] = "true"  # API expects boolean as string 'true'
            log.debug(f"Attempting upload to {len(selected_hosts)} hosts...")

            response = requests.post(upload_url, files=files, data=payload)
            response.raise_for_status()

            # --- Handle potential non-JSON success response ---
            # The successful upload response might not be JSON according to docs.
            # It lists parameters like name, hash, size, url etc., but not explicitly as JSON.
            # Let's try to parse as JSON, but fall back to text if it fails.
            try:
                data = response.json()
                log.debug("--- Upload Response (JSON) ---")
                log.debug(json.dumps(data, indent=2))
                # Check for API-level errors if response IS json
                if isinstance(data, dict) and data.get("error") and data.get("error") != "ok":
                    log.error(f"Upload API error: {data.get('error')}")
                    return None
                # Look for the file URL, structure might vary based on single/multi file
                file_url = None
                delete_url = None
                # Case 1: Response is a dict containing a 'files' list
                if (
                    isinstance(data, dict)
                    and "files" in data
                    and isinstance(data["files"], list)
                    and len(data["files"]) > 0
                ):
                    if isinstance(data["files"][0], dict) and "url" in data["files"][0]:
                        file_url = data["files"][0]["url"]
                        delete_url = data["files"][0]["deleteUrl"]
                # Case 2: Response is a list (less common?)
                elif (
                    isinstance(data, list)
                    and len(data) > 0
                    and isinstance(data[0], dict)
                    and "url" in data[0]
                ):
                    file_url = data[0]["url"]
                    delete_url = data[0]["deleteUrl"]
                # Case 3: Response is a simple dict with a top-level url (less common?)
                elif isinstance(data, dict) and "url" in data:
                    file_url = data["url"]
                    delete_url = data["deleteUrl"]

                if file_url:
                    log.info(f"Upload successful! File URL: {file_url}")
                    return file_url, delete_url
                else:
                    log.warning(
                        "Upload might be complete, but couldn't find the file URL in the response."
                    )
                    return "Completed (URL not found)"

            except json.JSONDecodeError:
                log.debug("--- Upload Response (Non-JSON Text) ---")
                log.debug(response.text)
                # Basic check for success keywords if not JSON
                # Use single quotes inside the double-quoted string to avoid termination issues
                if (
                    "upload success" in response.text.lower()
                    or '"error":"ok"' in response.text.lower()
                ):  # Check common success indicators
                    log.info(
                        "Upload likely successful (based on text response). "
                        "Please check your MultiUp account."
                    )
                    # Cannot reliably extract URL from non-JSON text
                    return "Completed (Check Account)"
                else:
                    log.error("Upload failed or response format unclear.")
                    return None

    except requests.exceptions.RequestException as e:
        log.error(f"Upload request failed: {e}")
        # It's helpful to see the response body for debugging if available
        if e.response is not None:
            log.error(f"Response status code: {e.response.status_code}")
            log.error(f"Response text: {e.response.text}")
        return None
    except OSError as e:
        log.error(f"Error reading file: {e}")
        return None
