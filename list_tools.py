"""List all available MCP tools"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp_servers.mcp_client import MCPClientManager
from source.avicenna.config import Config

async def show_tools():
    print("🔍 Discovering MCP Tools...\n")
    
    manager = MCPClientManager()
    config = Config.load_mcp_config()
    
    # Connect to all enabled servers
    results = await manager.connect_all(config.servers)
    
    print("=" * 70)
    print("CURRENTLY AVAILABLE TOOLS")
    print("=" * 70)
    
    # Show tools by server
    for server_name in sorted(results.keys()):
        if not results[server_name]:
            continue
            
        tools_for_server = [
            name for name, srv in manager.tool_to_server.items() 
            if srv == server_name
        ]
        
        if tools_for_server:
            print(f"\n📦 {server_name} ({len(tools_for_server)} tools)")
            print("-" * 70)
            for tool_name in sorted(tools_for_server):
                tool = manager.tools[tool_name]
                desc = tool.description or "No description"
                # Truncate long descriptions
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                print(f"  • {tool_name}")
                print(f"    {desc}")
    
    print("\n" + "=" * 70)
    print(f"TOTAL: {len(manager.tools)} tools from {len([r for r in results.values() if r])} servers")
    print("=" * 70)
    
    await manager.cleanup()

if __name__ == "__main__":
    asyncio.run(show_tools())
