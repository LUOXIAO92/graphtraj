# Task 644: template of the ONE local settings file the steps read (the same variables as Task 643's). Copy it to
#   scripts/verify-644/local/settings.zsh   (git-ignored; never commit it)
# and replace every value. All values below are fake placeholders. The steps STOP, naming the variable, when one is
# missing or empty, and when the file is not git-ignored or is tracked. No value is echoed by the steps; 00 prints the
# variable NAMES only (and a cost estimate on the console). Plain assignments only: the file is sourced by zsh.
# The evidence scrub replaces the values of PROJECT, ZONE, VM_NAME, MACHINE_TYPE, the label VALUES, PROVIDER_ID,
# PROVIDER_NAME, BASE_URL, MODEL, KEY_ENV and VM_USER (VM paths contain it): each must be distinctive (4+ characters,
# not an ordinary word found in drive644.py or steps.zsh), or 00 and V STOP naming the variable. NETWORK and label keys are not scrubbed.

# --- The cloud project and the VM -------------------------------------------------------------------------------
PROJECT=example-project-000000       # cloud project id; every gcloud command names it with --project
ZONE=example-zone1-a                 # zone of the VM (its region is derived by dropping the last '-x')
MACHINE_TYPE=example-machine-2       # machine type of the VM
VCPUS=2                              # vCPUs of MACHINE_TYPE (used only for the cost estimate)
VM_NAME=example-vm-name              # VM name; also its network tag and the stem of the Task rules <VM_NAME>-deny, <VM_NAME>-ssh
VM_LABELS=example-key=example-value  # labels put on the VM (gcloud --labels syntax), so D can find it
VM_USER=example-user                 # Windows account created from the instance's ssh-keys metadata (<= 20 chars)
NETWORK=example-network              # VPC network of the VM; the two Task firewall rules go there
IMAGE_FAMILY=example-image-family    # public Windows Server x64 image family
IMAGE_PROJECT=example-image-project  # public image project that hosts IMAGE_FAMILY
DISK_GB=64                           # boot disk size in GB (balanced persistent disk, deleted with the VM)

# --- The model provider Codex uses on the VM (written into the VM's %USERPROFILE%\.codex\config.toml) ------------
PROVIDER_ID=example-provider         # model_provider id in config.toml
PROVIDER_NAME=Example-Provider       # display name of that provider
BASE_URL=https://api.example.invalid/v1   # the provider's base URL
WIRE_API=responses                   # Codex wire API (Codex speaks only "responses")
MODEL=example-model                  # model id
KEY_ENV=EXAMPLE_API_KEY              # name of the VM user's environment variable that holds the temporary key (step K)

# --- Cost estimate (console only; per-hour list prices in USD, converted at EST_RATE) -----------------------------
PRICE_VM_USD_H=0.10                  # MACHINE_TYPE in ZONE's region, per hour
PRICE_WINLIC_USD_VCPU_H=0.05         # Windows Server licence, per vCPU per hour
PRICE_DISK_USD_GB_MONTH=0.10         # balanced persistent disk, per GB per month
PRICE_IP_USD_H=0.005                 # external IPv4 address in use, per hour
EST_CURRENCY=XXX                     # currency of the estimate
EST_RATE=100                         # EST_CURRENCY per USD
BUDGET=1000                          # the Task's cloud budget in EST_CURRENCY (00 prints the hours it covers)
