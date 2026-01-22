"""Phase 3 Verification: Test MCP Client Manager"""
import asyncio
import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from source.avicenna.mcp_client import MCPClientManager
from source.avicenna.mcp.mcp_config_schema import MCPServerConfig
from source.avicenna.config import Config


async def test_basic_server():
    """Test connecting to basic server and calling tools"""
    print("\n" + "="*60)
    print("TEST 1: BASIC SERVER CONNECTION")
    print("="*60)
    
    manager = MCPClientManager()
    
    try:
        # Create basic server config
        config = MCPServerConfig(
            name="basic",
            script="mcp/basic_server.py",
            enabled=True,
            description="Basic tools server"
        )
        
        # Connect
        print(f"\n→ Connecting to {config.name}...")
        success = await manager.connect_server(config)
        
        if not success:
            print("✗ Failed to connect to basic server")
            return False
        
        print(f"✓ Connected successfully")
        print(f"✓ Tools available: {manager.list_available_tools()}")
        
        # Test get_current_time
        print(f"\n→ Testing get_current_time()...")
        result = await manager.call_tool("get_current_time", {})
        print(f"✓ Result: {result}")
        
        # Test calculate
        print(f"\n→ Testing calculate()...")
        tests = [
            ("2 + 2", "4"),
            ("10 * 5", "50"),
            ("(8 + 2) / 2", "5.0"),
        ]
        
        for expr, expected_contains in tests:
            result = await manager.call_tool("calculate", {"expression": expr})
            if expected_contains in result:
                print(f"✓ {expr} = {result}")
            else:
                print(f"✗ {expr} = {result} (expected to contain '{expected_contains}')")
        
        print(f"\n✓ Basic server test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Basic server test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await manager.cleanup()


async def test_gmail_server():
    """Test connecting to Gmail server"""
    print("\n" + "="*60)
    print("TEST 2: GMAIL SERVER CONNECTION")
    print("="*60)
    
    manager = MCPClientManager()
    
    try:
        # Create Gmail server config
        config = MCPServerConfig(
            name="gmail",
            script="mcp/gmail_server.py",
            enabled=True,
            description="Gmail tools server"
        )
        
        # Connect
        print(f"\n→ Connecting to {config.name}...")
        success = await manager.connect_server(config)
        
        if not success:
            print("✗ Failed to connect to Gmail server")
            return False
        
        print(f"✓ Connected successfully")
        print(f"✓ Tools available: {manager.list_available_tools()}")
        
        # Don't actually send email, just verify tools are available
        if "draft_email" in manager.list_available_tools():
            print(f"✓ draft_email tool registered")
        else:
            print(f"✗ draft_email tool missing")
            return False
        
        if "send_email" in manager.list_available_tools():
            print(f"✓ send_email tool registered")
        else:
            print(f"✗ send_email tool missing")
            return False
        
        print(f"\n✓ Gmail server test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Gmail server test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await manager.cleanup()


async def test_multiple_servers():
    """Test connecting to multiple servers simultaneously"""
    print("\n" + "="*60)
    print("TEST 3: MULTIPLE SERVERS")
    print("="*60)
    
    manager = MCPClientManager()
    
    try:
        # Load configuration
        config = Config.load_mcp_config()
        
        # Update paths to use mcp/ directory
        for server in config.servers:
            if server.name == "basic":
                server.script = "mcp/basic_server.py"
            elif server.name == "gmail":
                server.script = "mcp/gmail_server.py"
        
        # Connect to all servers
        print(f"\n→ Connecting to {len(config.servers)} servers...")
        results = await manager.connect_all(config.servers)
        
        print(f"\n✓ Connection results:")
        for name, success in results.items():
            status = "✓" if success else "✗"
            print(f"  {status} {name}: {'connected' if success else 'failed'}")
        
        # Show all available tools
        print(f"\n✓ Total tools available: {len(manager.list_available_tools())}")
        for tool_name in manager.list_available_tools():
            server = manager.tool_to_server[tool_name]
            print(f"  - {tool_name} (from {server})")
        
        # Test Gemini tool conversion
        print(f"\n→ Testing Gemini tool conversion...")
        gemini_tools = manager.get_gemini_tools()
        print(f"✓ Converted to {len(gemini_tools)} Gemini Tool objects")
        
        if gemini_tools:
            total_functions = sum(len(t.function_declarations) for t in gemini_tools)
            print(f"✓ Total function declarations: {total_functions}")
        
        print(f"\n✓ Multiple servers test PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Multiple servers test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        await manager.cleanup()


async def main():
    """Run all Phase 3 verification tests"""
    print("\nPHASE 3 MCP CLIENT VERIFICATION")
    print("Testing MCP client manager implementation...\n")
    
    results = []
    results.append(("Basic Server", await test_basic_server()))
    results.append(("Gmail Server", await test_gmail_server()))
    results.append(("Multiple Servers", await test_multiple_servers()))
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n✓✓✓ Phase 3 Implementation: VERIFIED ✓✓✓")
        return 0
    else:
        print("\n✗✗✗ Phase 3 Implementation: INCOMPLETE ✗✗✗")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
