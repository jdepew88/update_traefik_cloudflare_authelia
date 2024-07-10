import sys
import yaml
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get environment variables
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
DOMAIN_NAME = os.getenv("DOMAIN_NAME")

if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ZONE_ID or not DOMAIN_NAME:
    print("Please ensure CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, and DOMAIN_NAME are set in the .env file.")
    sys.exit(1)

def add_cname_record_to_cloudflare(api_token, zone_id, cname_name, cname_target):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "type": "CNAME",
        "name": cname_name,
        "content": cname_target,
        "ttl": 1,  # Cloudflare interprets a TTL of 1 as "automatic"
        "proxied": True
    }
    
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code in [200, 201]:
        print(f"Successfully added CNAME record: {cname_name} -> {cname_target}")
    elif response.status_code == 409:
        print(f"CNAME record already exists: {cname_name} -> {cname_target}")
    else:
        print(f"Failed to add CNAME record: {response.status_code} - {response.text}")

# Ensure the script is executed with a config file path argument
if len(sys.argv) != 2:
    print("Usage: python update_traefik_and_cloudflare.py <path_to_config_file>")
    sys.exit(1)

# Get the path to the config file from the command-line argument
config_file = sys.argv[1]

# Load the existing dynamic config from the specified config file
with open(config_file, 'r') as file:
    config = yaml.safe_load(file)

# Create backups directory if it doesn't exist
backup_dir = './backups'
os.makedirs(backup_dir, exist_ok=True)

# Create a backup of the current config file with a timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_file = os.path.join(backup_dir, f"config_backup_{timestamp}.yml")
with open(backup_file, 'w') as file:
    yaml.dump(config, file)

print(f"Backup of the original config file saved as {backup_file}")

# Get input from the user
service_name = input("Enter the name of your service: ")
ip_address = input(f"Enter the IP address of {service_name}: ")
scheme = input("Enter the scheme (http or https) for the service: ").strip().lower()

# Validate scheme input
if scheme not in ['http', 'https']:
    print("Invalid scheme. Please enter 'http' or 'https'.")
    sys.exit(1)

# Create the new router entry
router_entry = {
    service_name: {
        'entryPoints': ['https'],
        'rule': f'Host(`{service_name}.{DOMAIN_NAME}`)',
        'middlewares': ['chain-no-auth'],
        'tls': {},
        'service': f'{service_name}-svc'
    }
}

# Create the new service entry
service_entry = {
    f'{service_name}-svc': {
        'loadBalancer': {
            'servers': [{'url': f'{scheme}://{ip_address}/'}],
            'passHostHeader': True
        }
    }
}

# Insert the new router entry in alphabetical order
routers = config['http']['routers']
routers.update(router_entry)
config['http']['routers'] = dict(sorted(routers.items()))

# Insert the new service entry in alphabetical order
services = config['http']['services']
services.update(service_entry)
config['http']['services'] = dict(sorted(services.items()))

# Save the updated config file, overwriting the original config.yml
with open(config_file, 'w') as file:
    yaml.dump(config, file)

print(f"Updated config file saved as {config_file}")

# Add the CNAME record to Cloudflare, pointing to the main domain
add_cname_record_to_cloudflare(CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID, f"{service_name}.{DOMAIN_NAME}", DOMAIN_NAME)

# Add a new subdomain to the Authelia configuration
new_subdomain = f"{service_name}.{DOMAIN_NAME}"

def update_authelia_config(authelia_config_path, new_subdomain):
    # Create backups directory for Authelia if it doesn't exist
    authelia_backup_dir = '/mnt/user/appdata/Authelia/backups'
    os.makedirs(authelia_backup_dir, exist_ok=True)

    # Create a backup of the current Authelia config file with a timestamp
    authelia_backup_file = os.path.join(authelia_backup_dir, f"configuration_backup_{timestamp}.yml")
    with open(authelia_config_path, 'r') as file:
        authelia_config = yaml.safe_load(file)
    with open(authelia_backup_file, 'w') as file:
        yaml.dump(authelia_config, file)

    print(f"Backup of the original Authelia config file saved as {authelia_backup_file}")

    # Update the Authelia config
    for rule in authelia_config['access_control']['rules']:
        if rule['policy'] == 'one_factor':
            rule['domain'].append(new_subdomain)
            break
    else:
        authelia_config['access_control']['rules'].append({
            'domain': [new_subdomain],
            'policy': 'one_factor'
        })
    with open(authelia_config_path, 'w') as file:
        yaml.dump(authelia_config, file)

authelia_config_path = '/mnt/user/appdata/Authelia/configuration.yml'
update_authelia_config(authelia_config_path, new_subdomain)

print(f"Authelia configuration updated with new subdomain {new_subdomain}")
