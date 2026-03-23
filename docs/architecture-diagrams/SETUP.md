# ENVIRONMENT SETUP RUNBOOK

Copy and paste the command blocks below in order. Use the section that matches your
OS (macOS or Ubuntu). Prerequisites run on both.

## 1. USAGE PROMPT (CURSOR/VSCODE)

To trigger diagram generation in Cursor, use:

```markdown
CONTEXT DIRECTORY: docs/architecture-diagrams
TASKS:
- Read the @docs/architecture-diagrams/AGENT.md for your system instructions.
- Once done, read the @docs/architecture-diagrams/INSTRUCTIONS.md and create the architectural diagrams.
```

## 2. PREREQUISITES CHECK

Run once before setup. Fix any failures before continuing.

```bash
# AWS CLI
command -v aws || { echo "ERROR: AWS CLI not found. Install: https://aws.amazon.com/cli/"; exit 1; }
aws --version
```

```bash
# jq
command -v jq || { echo "ERROR: jq not found. macOS: brew install jq; Ubuntu: sudo apt install jq"; exit 1; }
jq --version
```

```bash
# Terraform 1.14+
command -v terraform || { echo "ERROR: Terraform not found. Install: https://developer.hashicorp.com/terraform/install"; exit 1; }
terraform version
```

```bash
# AWS credentials (run aws sso login first if using SSO)
aws sts get-caller-identity || { echo "ERROR: Not logged in. Run 'aws sso login' or configure credentials."; exit 1; }
aws sts get-caller-identity --query 'Arn' --output text
```

```bash
# Python 3 and Graphviz
command -v python3 || { echo "ERROR: python3 not found."; exit 1; }
python3 --version
command -v dot || { echo "ERROR: Graphviz (dot) not found. Install graphviz for your OS."; exit 1; }
dot -V
```

## 3. MACOS RUNBOOK

### 3.1 Install Homebrew (if needed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Add Homebrew to PATH if the installer tells you to.

### 3.2 Install Python 3 and Graphviz

```bash
brew install python3 graphviz
which dot
dot -V
python3 --version
```

### 3.3 Go to diagram project directory

```bash
cd "$(git rev-parse --show-toplevel)/docs/architecture-diagrams"
```

### 3.4 Create and activate virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3.5 Install pygraphviz (macOS: use Homebrew paths)

```bash
pip install --config-settings="--global-option=build_ext" \
  --config-settings="--global-option=-I$(brew --prefix graphviz)/include/" \
  --config-settings="--global-option=-L$(brew --prefix graphviz)/lib/" \
  pygraphviz
```

### 3.6 Install diagram Python packages

```bash
pip install diagrams graphviz graphviz2drawio
```

### 3.7 Verify (macOS)

```bash
pip list | grep -E 'diagrams|graphviz|pygraphviz'
```

## 4. UBUNTU RUNBOOK

### 4.1 Update and install system packages

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv build-essential graphviz libgraphviz-dev pkg-config
python3 --version
which dot
dot -V
```

### 4.2 Go to diagram project directory

```bash
cd "$(git rev-parse --show-toplevel)/docs/architecture-diagrams"
```

### 4.3 Create and activate virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4.4 Upgrade pip and install pygraphviz

```bash
pip install --upgrade pip setuptools wheel
pip install pygraphviz
```

If that fails, use explicit paths:

```bash
pip install --global-option=build_ext \
  --global-option="-I/usr/include/graphviz" \
  --global-option="-L/usr/lib/graphviz/" \
  pygraphviz
```

### 4.5 Install diagram Python packages

```bash
pip install diagrams graphviz graphviz2drawio
```

### 4.6 Verify (Ubuntu)

```bash
pip list | grep -E 'diagrams|graphviz|pygraphviz'
```

## 5. IDE EXTENSION (OPTIONAL)

**Draw.io (view/edit .drawio):**

```bash
cursor --install-extension hediet.vscode-drawio
```

**Graphviz (.dot preview):**

```bash
cursor --install-extension joaompinto.vscode-graphviz
```

## 6. TEST SETUP

From repo root, with venv activated and from `docs/architecture-diagrams`:

```bash
cd "$(git rev-parse --show-toplevel)/docs/architecture-diagrams"
source venv/bin/activate
mkdir -p diagrams
```

```bash
cat << 'PYEOF' > test_setup.py
from diagrams import Diagram, Cluster
from diagrams.aws.compute import EC2
from diagrams.aws.network import VPC

with Diagram("Test Setup", filename="diagrams/test", outformat=["png", "dot"], show=False):
    with Cluster("VPC"):
        vpc = VPC("vpc")
        vm = EC2("test-vm")
        vpc >> vm

print("Diagram generation OK")

import subprocess
subprocess.run(["graphviz2drawio", "diagrams/test.dot", "-o", "diagrams/test.drawio"], check=True)
print("Draw.io conversion OK")
PYEOF
```

```bash
python test_setup.py
```

If both lines print OK and `diagrams/test.drawio` exists, setup is correct.

## 7. DAILY WORKFLOW

### Activate and work

```bash
cd "$(git rev-parse --show-toplevel)/docs/architecture-diagrams"
source venv/bin/activate
```

### Deactivate when done

```bash
deactivate
```

## 8. TROUBLESHOOTING (COPY-PASTE FIXES)

### "ExecutableNotFound: failed to execute 'dot'"

```bash
# macOS
brew install graphviz

# Ubuntu
sudo apt install -y graphviz
which dot && dot -V
```

### "graphviz/cgraph.h file not found" (macOS)

Re-run step 3.5 (pygraphviz with `brew --prefix graphviz` paths).

### pygraphviz build failure (Ubuntu)

```bash
sudo apt install -y libgraphviz-dev pkg-config build-essential
pip install pygraphviz
```

### "No module named 'diagrams'"

```bash
source venv/bin/activate
pip install diagrams graphviz graphviz2drawio
```

### Wrong icon names in scripts

Use `EC2`, `RDS`, `S3` (case-sensitive). Inspect:

```bash
python3 -c "from diagrams.aws import compute; print([x for x in dir(compute) if not x.startswith('_')])"
```

## 9. PACKAGE SUMMARY

- **System (macOS):** `graphviz` (Homebrew)
- **System (Ubuntu):** `graphviz`, `libgraphviz-dev`, `pkg-config`, `build-essential`
- **Python (pip):** `pygraphviz`, `diagrams`, `graphviz`, `graphviz2drawio`
  (see steps above for install order)

## IDE AND EXTENSION GUIDE

### Install Draw.io via GUI

1. Open VS Code or Cursor
2. Extensions icon in the sidebar (or `Cmd+Shift+X` / `Ctrl+Shift+X`)
3. Search for "Draw.io Integration"
4. Install the extension by **hediet.vscode-drawio**
5. Restart the editor if prompted

### Using the Draw.io extension

- **View `.drawio` files:** Click a `.drawio` file in the explorer to open it in
  the Draw.io editor inside the IDE
- **Edit diagrams:** Full graphical editor with drag-and-drop
- **Export:** Right-click an open diagram and choose export (PNG, SVG, PDF)
- **Preview PNG:** Click PNG files in the explorer to preview in the editor

### Viewing diagrams in the IDE

- **PNG:** Click to preview
- **`.drawio`:** Click to open in the Draw.io editor for editing
- **Split view:** Open the Python script and the generated diagram side-by-side

### Alternative extensions

- **Graphviz Preview** (joaompinto.vscode-graphviz): Preview `.dot` files in the
  editor

  ```bash
  cursor --install-extension joaompinto.vscode-graphviz
  ```

- **Image preview:** Built into VS Code/Cursor; no install needed for PNG

## USING AI ASSISTANTS (CURSOR / COPILOT)

After setup, you can use the agent or chat to generate diagram scripts. Sample prompts:

### Sample prompt: three-tier web application

```text
Create a Python script using the diagrams library to generate an AWS architecture
diagram for a three-tier web application with the following components:

1. Frontend tier:
  - CloudFront for global content delivery
  - Application Load Balancer (ALB) in a public subnet
  - Background color: light blue (#E3F2FD)

2. Application tier:
  - 2 EC2 instances in an Auto Scaling group within private app subnet
  - Lambda as an alternative serverless compute option
  - Background color: light purple (#F3E5F5)

3. Data tier:
  - RDS (PostgreSQL/MySQL) with read replica
  - S3 bucket for object storage
  - Background color: light orange (#FFF3E0)

4. Security and monitoring:
  - AWS Secrets Manager for secrets management
  - Connection from EC2 to Secrets Manager (dotted line labeled "Secrets")
  - CloudWatch connected to all tiers (dotted green lines)

Requirements:
- Use orthogonal splines for clean lines
- Generate PNG, DOT, and convert to DRAWIO format
- Save output to diagrams/three_tier_web_app
- Group related resources in clusters with appropriate styling
- Add meaningful edge labels (HTTPS, SQL, etc.)
```

### Sample prompt: parse Terraform IaC

```text
Create a Python script that parses Terraform configuration files and automatically
generates an AWS architecture diagram. The script should:

1. Read all .tf files in the directory
2. Extract AWS resources using regex: resource "aws_*" "resource_name"
3. Map Terraform resource types to diagrams library icons (e.g. aws_vpc to VPC,
   aws_subnet to subnet, aws_instance to EC2, aws_s3_bucket to S3, aws_db_instance
   to RDS)
4. Detect relationships via depends_on and resource references
5. Group subnets within VPC clusters and use background colors for tiers
6. Generate PNG, DOT, and DRAWIO; use orthogonal layout with nodesep=0.8,
   ranksep=1.2
7. Save output to diagrams/terraform_parsed_architecture
```

### Tips for effective prompts

1. **Be specific:** List exact AWS services and layout (orthogonal lines,
   spacing, TB/LR)
2. **Include styling:** Background colors, edge styles, labels
3. **Define grouping:** Clusters, tiers, subnets
4. **Request formats:** Ask for PNG, DOT, and DRAWIO
5. **Reference AGENT.md:** Ask the AI to follow patterns in AGENT.md for consistency

### Example workflow with AI

1. Paste a prompt (e.g. one of the samples above)
2. Review the generated script (imports, icon names are case-sensitive)
3. Run: `python your_diagram_script.py`
4. Fix any import or icon errors
5. Open the `.drawio` file in the IDE to view or edit
6. Iterate: ask for color/layout changes or extra components
7. Use the Draw.io editor for final tweaks

## MORE TROUBLESHOOTING

### Permission denied when installing packages

Always use a virtual environment. Do not use `sudo pip`.

### Draw.io extension not opening `.drawio` files

1. Right-click the `.drawio` file
2. "Open With..."
3. Choose "Draw.io Editor"
4. Check "Configure file association for '.drawio'"

### AI-generated script has wrong icon names

Icon class names are case-sensitive. Common mistakes:

- Wrong: `Ec2` → use: `EC2`
- Wrong: `Rds` → use: `RDS`
- Wrong: `S3Bucket` → use: `S3`

To list available icons:

```python
from diagrams.aws import compute, network, database
print(dir(compute))
print(dir(network))
print(dir(database))
```

## TESTING YOUR SETUP (DETAILED)

After running the test in section 6:

1. Confirm both "Diagram generation OK" and "Draw.io conversion OK" appear
2. Check that `diagrams/test.png`, `diagrams/test.dot`, and
   `diagrams/test.drawio` exist
3. Open `diagrams/test.drawio` in VS Code/Cursor with the Draw.io extension to
   confirm the IDE can display and edit the diagram

## FULL PACKAGE REFERENCE

### System

- **macOS:** `graphviz` (Homebrew)
- **Ubuntu:** `graphviz`, `libgraphviz-dev`, `pkg-config`, `build-essential`

### Python (pip)

**Core:** `pygraphviz` (special install on macOS), `diagrams`, `graphviz`,
`graphviz2drawio`

**Auto-installed:** `jinja2`, `MarkupSafe`, `puremagic`, `svg.path`, `pre-commit`
and its dependencies

### Optional

- **AWS icons:** Provided by `diagrams.aws.*`; no extra packages
- **CloudFormation parsing:** `boto3`, `troposphere` if you add template parsing
