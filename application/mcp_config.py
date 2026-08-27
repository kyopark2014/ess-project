import logging
import sys
import utils
import os
import boto3

logging.basicConfig(
    level=logging.INFO,  # Default to INFO level
    format='%(filename)s:%(lineno)d | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("mcp-config")

script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, "config.json")

config = utils.load_config()
logger.info(f"config: {config}")

region = config["region"] if "region" in config else "us-west-2"
projectName = config["projectName"] if "projectName" in config else "mcp"
workingDir = os.path.dirname(os.path.abspath(__file__))
logger.info(f"workingDir: {workingDir}")

mcp_user_config = {}    

def get_agentcore_gateway_mcp_url(gateway_name: str, gateway_region: str) -> str | None:
    client = boto3.client("bedrock-agentcore-control", region_name=gateway_region)
    try:
        response = client.list_gateways()
        for item in response.get("items", []):
            if item.get("name") != gateway_name:
                continue

            gateway_id = item["gatewayId"]
            gateway = client.get_gateway(gatewayIdentifier=gateway_id)
            return gateway["gatewayUrl"].rstrip("/")
    except Exception as e:
        logger.error(f"Error resolving AgentCore gateway URL for {gateway_name}: {e}")

    return None
    
def load_config(mcp_type):
    # Display-name aliases (aligned with agentic-work mcp.list)
    if mcp_type == "knowledge base":
        mcp_type = "kb-retriever"
    elif mcp_type == "image generation":
        mcp_type = "image_generation"

    if mcp_type == "image_generation":
        return {
            "mcpServers": {
                "imageGeneration": {
                    "command": "python",
                    "args": [
                        f"{workingDir}/mcp_server_image_generation.py"
                    ],
                    "env": {
                        "PYTHONPATH": workingDir,
                        # AGENTCORE_USER_ID is injected at runtime in chat.create_agent()
                    },
                }
            }
        }
    
    elif mcp_type == "kb-retriever":
        return {
            "mcpServers": {
                "kb_retriever": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_retrieve.py"],
                    "env": {
                        "PYTHONPATH": workingDir,
                        # AGENTCORE_USER_ID is injected at runtime in chat.create_agent()
                    },
                }
            }
        }

    elif mcp_type == "web_fetch":
        return {
            "mcpServers": {
                "web_fetch": {
                    "command": "npx",
                    "args": ["-y", "mcp-server-fetch-typescript"]
                }
            }
        }
    
    elif mcp_type == "text_extraction":
        return {
            "mcpServers": {
                "text_extraction": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_text_extraction.py"]
                }
            }
        }

    elif mcp_type == "memory":
        return {
            "mcpServers": {
                "memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_memory.py"],
                    "env": {
                        "PYTHONPATH": workingDir,
                        # AGENTCORE_USER_ID is injected at runtime in langgraph_agent.create_agent()
                    },
                }
            }
        }

    elif mcp_type == "graph memory":
        return {
            "mcpServers": {
                "graph memory": {
                    "command": "python",
                    "args": [f"{workingDir}/mcp_server_graph_memory.py"],
                    "env": {
                        "PYTHONPATH": workingDir,
                        # AGENTCORE_USER_ID is injected at runtime in chat.create_agent()
                    },
                }
            }
        }

    elif mcp_type == "websearch":
        gateway_url = get_agentcore_gateway_mcp_url("gateway-websearch", "us-east-1")
        if not gateway_url:
            logger.info(
                "AgentCore gateway websearch MCP skipped: "
                "gateway-websearch not found in us-east-1."
            )
            return {}
        return {
            "mcpServers": {
                "gateway-websearch": {
                    "type": "streamable_http",
                    "url": gateway_url,
                    "auth_type": "aws_sigv4",
                    "auth_region": "us-east-1",
                    "auth_service": "bedrock-agentcore",
                }
            }
        }

    elif mcp_type == "사용자 설정":
        return mcp_user_config

def load_selected_config(mcp_servers: dict):
    logger.info(f"mcp_servers: {mcp_servers}")
    
    loaded_config = {}
    for server in mcp_servers:
        config = load_config(server)
        if config:
            loaded_config.update(config["mcpServers"])
    return {
        "mcpServers": loaded_config
    }
