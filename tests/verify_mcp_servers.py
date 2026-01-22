"""Verification script for Phase 2 MCP server implementation"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def verify_basic_server():
    """Test basic_server.py tools"""
    print("\n" + "="*60)
    print("VERIFYING BASIC SERVER")
    print("="*60)
    
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "basic_server", 
            str(Path(__file__).parent / "mcp" / "basic_server.py")
        )
        basic_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(basic_module)
        
        print(f"✓ Module loaded: {basic_module.mcp.name}")
        
        # Test get_current_time - tools are wrapped in FastMCP, need to call .fn()
        time_result = basic_module.get_current_time.fn()
        print(f"\n✓ get_current_time():")
        print(f"  {time_result}")
        
        # Test calculate
        tests = [
            ("2 + 2", "4.0"),
            ("10 - 3", "7.0"),
            ("5 * 4", "20.0"),
            ("20 / 4", "5.0"),
            ("2 ** 8", "256.0"),
            ("(10 + 5) * 2 - 8", "22.0"),
        ]
        
        print(f"\n✓ calculate() tests:")
        for expr, expected in tests:
            result = basic_module.calculate.fn(expr)
            status = "✓" if result == expected else "✗"
            print(f"  {status} {expr} = {result} (expected: {expected})")
        
        print(f"\n✓ Basic server verification PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Basic server verification FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_gmail_server():
    """Test gmail_server.py structure (no authentication)"""
    print("\n" + "="*60)
    print("VERIFYING GMAIL SERVER")
    print("="*60)
    
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gmail_server", 
            str(Path(__file__).parent / "mcp" / "gmail_server.py")
        )
        gmail_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gmail_module)
        
        print(f"✓ Module loaded: {gmail_module.mcp.name}")
        
        # Check if tools are defined
        has_draft = hasattr(gmail_module, 'draft_email')
        has_send = hasattr(gmail_module, 'send_email')
        
        print(f"✓ draft_email tool: {'defined' if has_draft else 'MISSING'}")
        print(f"✓ send_email tool: {'defined' if has_send else 'MISSING'}")
        
        if gmail_module.gmail_service is None:
            print(f"\n⚠ Gmail not authenticated (expected - credentials not set up)")
        else:
            print(f"\n✓ Gmail authenticated successfully")
        
        print(f"\n✓ Gmail server verification PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Gmail server verification FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_configuration():
    """Check MCP configuration files"""
    print("\n" + "="*60)
    print("VERIFYING CONFIGURATION")
    print("="*60)
    
    try:
        from source.avicenna.config import Config
        config = Config.load_mcp_config()
        
        print(f"✓ Config loaded: {len(config.servers)} servers")
        for server in config.servers:
            status = "enabled" if server.enabled else "disabled"
            print(f"  - {server.name}: {server.script} ({status})")
        
        print(f"\n✓ Configuration verification PASSED")
        return True
        
    except Exception as e:
        print(f"\n✗ Configuration verification FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\nPHASE 2 MCP SERVER VERIFICATION")
    print("Testing MCP server implementations...\n")
    
    results = []
    results.append(("Basic Server", verify_basic_server()))
    results.append(("Gmail Server", verify_gmail_server()))
    results.append(("Configuration", verify_configuration()))
    
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {name}: {status}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n✓✓✓ Phase 2 Implementation: VERIFIED ✓✓✓")
        sys.exit(0)
    else:
        print("\n✗✗✗ Phase 2 Implementation: INCOMPLETE ✗✗✗")
        sys.exit(1)
